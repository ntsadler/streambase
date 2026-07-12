#!/usr/bin/env python3
import json
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import requests

from src.database import connect, init_db
from src.settings import DB_PATH
from src.spotify_api import SpotifyAPI, extract_playlist_id


SOURCE = "viberate_cyanite_seed"


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def init_tables(db_path):
    with connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS spotify_playlist_tracks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                playlist_url TEXT NOT NULL,
                spotify_playlist_id TEXT,
                spotify_track_id TEXT,
                track_name TEXT,
                artist_names TEXT,
                spotify_url TEXT,
                raw_json TEXT,
                fetched_at TEXT,
                UNIQUE(playlist_url, spotify_track_id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS spotify_playlist_tracklist_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                playlist_url TEXT NOT NULL UNIQUE,
                spotify_playlist_id TEXT,
                status TEXT DEFAULT 'planned',
                track_count INTEGER DEFAULT 0,
                error TEXT,
                fetched_at TEXT,
                updated_at TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS spotify_cyanite_playlist_overlaps (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                catalog_song_id INTEGER NOT NULL,
                catalog_title TEXT,
                playlist_url TEXT NOT NULL,
                playlist_name TEXT,
                exact_track_overlap_count INTEGER DEFAULT 0,
                artist_overlap_count INTEGER DEFAULT 0,
                overlap_track_ids TEXT,
                overlap_artist_names TEXT,
                score REAL DEFAULT 0,
                computed_at TEXT,
                UNIQUE(catalog_song_id, playlist_url)
            )
            """
        )
        conn.commit()


def candidate_playlists(db_path, limit):
    sql = """
        SELECT playlist_url, MAX(playlist_name) AS playlist_name
        FROM viberate_cyanite_playlist_matches
        WHERE coalesce(playlist_url, '') != ''
        GROUP BY playlist_url
        ORDER BY MAX(updated_at) DESC
    """
    if limit:
        sql += " LIMIT ?"
        args = (int(limit),)
    else:
        args = ()
    with connect(db_path) as conn:
        return [dict(row) for row in conn.execute(sql, args).fetchall()]


def playlist_already_fetched(db_path, playlist_url):
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT status, track_count FROM spotify_playlist_tracklist_runs WHERE playlist_url=?",
            (playlist_url,),
        ).fetchone()
    return dict(row) if row else {}


def save_playlist_tracks(db_path, playlist_url, playlist_id, track_items):
    now = utc_now()
    saved = 0
    with connect(db_path) as conn:
        for item in track_items:
            track = item.get("track") or {}
            track_id = track.get("id") or ""
            if not track_id:
                continue
            artists = [a.get("name", "") for a in track.get("artists", []) if a.get("name")]
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO spotify_playlist_tracks (
                    playlist_url, spotify_playlist_id, spotify_track_id, track_name,
                    artist_names, spotify_url, raw_json, fetched_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    playlist_url,
                    playlist_id,
                    track_id,
                    track.get("name") or "",
                    "; ".join(artists),
                    (track.get("external_urls") or {}).get("spotify", ""),
                    json.dumps(item, ensure_ascii=True),
                    now,
                ),
            )
            saved += cur.rowcount
        conn.execute(
            """
            INSERT INTO spotify_playlist_tracklist_runs (
                playlist_url, spotify_playlist_id, status, track_count, error, fetched_at, updated_at
            ) VALUES (?, ?, 'completed', ?, '', ?, ?)
            ON CONFLICT(playlist_url) DO UPDATE SET
                spotify_playlist_id=excluded.spotify_playlist_id,
                status='completed',
                track_count=excluded.track_count,
                error='',
                fetched_at=excluded.fetched_at,
                updated_at=excluded.updated_at
            """,
            (playlist_url, playlist_id, len(track_items), now, now),
        )
        conn.commit()
    return saved


def mark_playlist_failed(db_path, playlist_url, playlist_id, error):
    now = utc_now()
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO spotify_playlist_tracklist_runs (
                playlist_url, spotify_playlist_id, status, track_count, error, updated_at
            ) VALUES (?, ?, 'failed', 0, ?, ?)
            ON CONFLICT(playlist_url) DO UPDATE SET
                status='failed',
                error=excluded.error,
                updated_at=excluded.updated_at
            """,
            (playlist_url, playlist_id, str(error)[:1000], now),
        )
        conn.commit()


def norm_artist(value):
    return " ".join(str(value or "").lower().replace("&", "and").split())


def compute_overlaps(db_path):
    now = utc_now()
    with connect(db_path) as conn:
        seeds = [dict(row) for row in conn.execute(
            """
            SELECT catalog_song_id, catalog_title, spotify_track_id, result_artist
            FROM cyanite_similarity_seed_songs
            """
        ).fetchall()]
        tracks = [dict(row) for row in conn.execute(
            """
            SELECT playlist_url, spotify_track_id, artist_names
            FROM spotify_playlist_tracks
            """
        ).fetchall()]
        playlists = {
            row["playlist_url"]: dict(row)
            for row in conn.execute(
                """
                SELECT playlist_url, MAX(playlist_name) AS playlist_name
                FROM viberate_cyanite_playlist_matches
                GROUP BY playlist_url
                """
            ).fetchall()
        }
        seed_by_song = {}
        for seed in seeds:
            song_id = int(seed["catalog_song_id"])
            bucket = seed_by_song.setdefault(
                song_id,
                {
                    "catalog_title": seed["catalog_title"],
                    "track_ids": set(),
                    "artists": set(),
                },
            )
            if seed.get("spotify_track_id"):
                bucket["track_ids"].add(seed["spotify_track_id"])
            if seed.get("result_artist"):
                bucket["artists"].add(norm_artist(seed["result_artist"]))
        playlist_tracks = {}
        for track in tracks:
            bucket = playlist_tracks.setdefault(track["playlist_url"], {"track_ids": set(), "artists": set()})
            if track.get("spotify_track_id"):
                bucket["track_ids"].add(track["spotify_track_id"])
            for artist in str(track.get("artist_names") or "").split(";"):
                clean = norm_artist(artist)
                if clean:
                    bucket["artists"].add(clean)

        rows_written = 0
        for playlist_url, pdata in playlist_tracks.items():
            for song_id, seed_data in seed_by_song.items():
                track_overlap = seed_data["track_ids"] & pdata["track_ids"]
                artist_overlap = seed_data["artists"] & pdata["artists"]
                if not track_overlap and not artist_overlap:
                    continue
                exact_count = len(track_overlap)
                artist_count = len(artist_overlap)
                score = min(100, exact_count * 35 + artist_count * 12)
                conn.execute(
                    """
                    INSERT INTO spotify_cyanite_playlist_overlaps (
                        catalog_song_id, catalog_title, playlist_url, playlist_name,
                        exact_track_overlap_count, artist_overlap_count,
                        overlap_track_ids, overlap_artist_names, score, computed_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(catalog_song_id, playlist_url) DO UPDATE SET
                        playlist_name=excluded.playlist_name,
                        exact_track_overlap_count=excluded.exact_track_overlap_count,
                        artist_overlap_count=excluded.artist_overlap_count,
                        overlap_track_ids=excluded.overlap_track_ids,
                        overlap_artist_names=excluded.overlap_artist_names,
                        score=excluded.score,
                        computed_at=excluded.computed_at
                    """,
                    (
                        song_id,
                        seed_data["catalog_title"],
                        playlist_url,
                        (playlists.get(playlist_url) or {}).get("playlist_name", ""),
                        exact_count,
                        artist_count,
                        "; ".join(sorted(track_overlap)),
                        "; ".join(sorted(artist_overlap)),
                        score,
                        now,
                    ),
                )
                rows_written += 1
                conn.execute(
                    """
                    UPDATE song_playlist_targets
                    SET fit_score = max(coalesce(fit_score, 0), ?),
                        notes = CASE
                            WHEN ? > 0 THEN 'Spotify verified exact Cyanite seed-track overlap'
                            ELSE 'Spotify verified Cyanite seed-artist overlap'
                        END,
                        updated_at = ?
                    WHERE song_id = ? AND playlist_url = ?
                    """,
                    (score, exact_count, now, song_id, playlist_url),
                )
        conn.commit()
    return rows_written


def main():
    init_db(DB_PATH)
    init_tables(DB_PATH)
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    client = SpotifyAPI()
    if not client.configured:
        print(json.dumps({
            "ok": False,
            "error": "Spotify credentials are not configured. Add SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET to .env.",
        }, indent=2))
        return 1

    fetched = 0
    skipped = 0
    failed = []
    for playlist in candidate_playlists(DB_PATH, limit):
        playlist_url = playlist["playlist_url"]
        playlist_id = extract_playlist_id(playlist_url)
        prior = playlist_already_fetched(DB_PATH, playlist_url)
        if prior.get("status") == "completed":
            skipped += 1
            continue
        try:
            track_items = client.get_playlist_tracks(playlist_url, limit=1000)
            save_playlist_tracks(DB_PATH, playlist_url, playlist_id, track_items)
            fetched += 1
        except requests.RequestException as exc:
            mark_playlist_failed(DB_PATH, playlist_url, playlist_id, exc)
            failed.append({"playlist_url": playlist_url, "error": str(exc)})
        time.sleep(0.4)

    overlaps = compute_overlaps(DB_PATH)
    with connect(DB_PATH) as conn:
        summary = {
            "ok": not failed,
            "fetched_playlists": fetched,
            "skipped_playlists": skipped,
            "failed_playlists": len(failed),
            "stored_track_rows": conn.execute("SELECT COUNT(*) FROM spotify_playlist_tracks").fetchone()[0],
            "overlap_rows": conn.execute("SELECT COUNT(*) FROM spotify_cyanite_playlist_overlaps").fetchone()[0],
            "exact_overlap_rows": conn.execute(
                "SELECT COUNT(*) FROM spotify_cyanite_playlist_overlaps WHERE exact_track_overlap_count > 0"
            ).fetchone()[0],
            "artist_overlap_rows": conn.execute(
                "SELECT COUNT(*) FROM spotify_cyanite_playlist_overlaps WHERE artist_overlap_count > 0"
            ).fetchone()[0],
            "failed": failed[:10],
        }
    print(json.dumps(summary, indent=2))
    return 0 if not failed else 2


if __name__ == "__main__":
    raise SystemExit(main())
