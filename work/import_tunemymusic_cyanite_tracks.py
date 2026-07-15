#!/usr/bin/env python3
"""Import a TuneMyMusic Spotify-to-file export as Cyanite seed track references."""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import unicodedata
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.database import connect, init_db, now  # noqa: E402
from src.settings import DB_PATH, local_data_path  # noqa: E402

SOURCE = "tunemymusic_csv"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize_name(value: str) -> str:
    value = unicodedata.normalize("NFKC", value or "").strip().lower()
    return re.sub(r"\s+", " ", value)


def ensure_tables() -> None:
    with connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS cyanite_seed_playlist_track_harvest_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                playlist_url TEXT UNIQUE,
                spotify_playlist_id TEXT,
                playlist_name TEXT,
                source_song_ids TEXT,
                status TEXT DEFAULT 'planned',
                request_count INTEGER DEFAULT 0,
                track_count INTEGER DEFAULT 0,
                mapped_row_count INTEGER DEFAULT 0,
                error TEXT,
                started_at TEXT,
                completed_at TEXT,
                updated_at TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS cyanite_seed_song_playlist_tracks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                song_id INTEGER NOT NULL,
                song_title TEXT,
                playlist_url TEXT NOT NULL,
                playlist_name TEXT,
                spotify_playlist_id TEXT,
                track_position INTEGER DEFAULT 0,
                spotify_track_id TEXT,
                track_name TEXT,
                artist_names TEXT,
                album_name TEXT,
                album_release_date TEXT,
                isrc TEXT,
                popularity INTEGER DEFAULT 0,
                duration_ms INTEGER DEFAULT 0,
                explicit INTEGER DEFAULT 0,
                track_url TEXT,
                raw_json TEXT,
                fetched_at TEXT,
                updated_at TEXT,
                UNIQUE(song_id, playlist_url, track_url)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS cyanite_seed_playlist_tracks (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               playlist_url TEXT,
               playlist_name TEXT,
               track_name TEXT,
               track_url TEXT,
               artist_names TEXT,
               source_song_ids TEXT,
               raw_json TEXT,
               created_at TEXT,
               updated_at TEXT,
               UNIQUE(playlist_url, track_url)
            )
            """
        )
        conn.commit()


def load_seed_playlists() -> dict[str, list[dict]]:
    with connect(DB_PATH) as conn:
        rows = conn.execute(
            """
            SELECT
                spt.song_id,
                COALESCE(s.title, '') AS song_title,
                spt.playlist_name,
                spt.playlist_url,
                COALESCE(p.spotify_playlist_id, '') AS spotify_playlist_id
            FROM song_playlist_targets spt
            LEFT JOIN songs s ON s.id = spt.song_id
            LEFT JOIN playlists p ON p.url = spt.playlist_url
            WHERE spt.source = 'cyanite_seed'
              AND COALESCE(spt.playlist_name, '') != ''
              AND COALESCE(spt.playlist_url, '') != ''
            ORDER BY spt.playlist_name, spt.playlist_url, spt.song_id
            """
        ).fetchall()
    by_name: dict[str, list[dict]] = defaultdict(list)
    seen = set()
    for row in rows:
        item = dict(row)
        key = (
            normalize_name(item["playlist_name"]),
            int(item["song_id"] or 0),
            item["playlist_url"],
        )
        if key in seen:
            continue
        seen.add(key)
        by_name[key[0]].append(item)
    return by_name


def track_url(spotify_track_id: str) -> str:
    spotify_track_id = (spotify_track_id or "").strip()
    return f"https://open.spotify.com/track/{spotify_track_id}" if spotify_track_id else ""


def import_csv(csv_path: Path, dry_run: bool = False) -> dict:
    seed_by_name = load_seed_playlists()
    imported_at = utc_now()
    summary = {
        "ok": True,
        "source_file": str(csv_path),
        "csv_rows": 0,
        "matched_csv_rows": 0,
        "unmatched_csv_rows": 0,
        "matched_playlist_names": 0,
        "unmatched_playlist_names": [],
        "ambiguous_playlist_names": {},
        "song_track_rows_upserted": 0,
        "playlist_track_rows_upserted": 0,
        "playlist_runs_marked": 0,
        "distinct_tracks": 0,
        "distinct_artists": 0,
    }

    playlist_track_counts: dict[str, int] = defaultdict(int)
    matched_names = set()
    unmatched_names = set()
    ambiguous_names: dict[str, int] = {}

    with csv_path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
    summary["csv_rows"] = len(rows)

    if dry_run:
        for row in rows:
            playlist_name = row.get("Playlist name") or ""
            matches = seed_by_name.get(normalize_name(playlist_name), [])
            if matches:
                matched_names.add(playlist_name)
                summary["matched_csv_rows"] += 1
                if len({m["playlist_url"] for m in matches}) > 1:
                    ambiguous_names[playlist_name] = len({m["playlist_url"] for m in matches})
            else:
                unmatched_names.add(playlist_name)
                summary["unmatched_csv_rows"] += 1
        summary["matched_playlist_names"] = len(matched_names)
        summary["unmatched_playlist_names"] = sorted(unmatched_names)
        summary["ambiguous_playlist_names"] = dict(sorted(ambiguous_names.items()))
        return summary

    with connect(DB_PATH) as conn:
        for row_index, row in enumerate(rows, start=1):
            playlist_name = row.get("Playlist name") or ""
            matches = seed_by_name.get(normalize_name(playlist_name), [])
            if not matches:
                unmatched_names.add(playlist_name)
                summary["unmatched_csv_rows"] += 1
                continue
            matched_names.add(playlist_name)
            summary["matched_csv_rows"] += 1
            urls = {m["playlist_url"] for m in matches}
            if len(urls) > 1:
                ambiguous_names[playlist_name] = len(urls)

            spotify_track_id = (row.get("Spotify - id") or "").strip()
            url = track_url(spotify_track_id)
            if not url:
                url = f"tunemymusic:{normalize_name(playlist_name)}:{row_index}"
            track = {
                "track_position": row_index,
                "spotify_track_id": spotify_track_id,
                "track_name": row.get("Track name") or "",
                "artist_names": row.get("Artist name") or "",
                "album_name": row.get("Album") or "",
                "album_release_date": "",
                "isrc": row.get("ISRC") or "",
                "popularity": 0,
                "duration_ms": 0,
                "explicit": 0,
                "track_url": url,
                "raw_json": json.dumps(
                    {"source": SOURCE, "csv_row": row_index, "row": row},
                    ensure_ascii=True,
                ),
            }

            matches_by_url: dict[str, list[dict]] = defaultdict(list)
            for match in matches:
                matches_by_url[match["playlist_url"]].append(match)

            for playlist_url, source_rows in matches_by_url.items():
                source_song_ids = ",".join(str(int(item["song_id"] or 0)) for item in source_rows)
                spotify_playlist_id = source_rows[0].get("spotify_playlist_id") or ""
                playlist_track_counts[playlist_url] += 1
                cur = conn.execute(
                    """
                    INSERT INTO cyanite_seed_playlist_tracks (
                        playlist_url, playlist_name, track_name, track_url, artist_names,
                        source_song_ids, raw_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(playlist_url, track_url) DO UPDATE SET
                        playlist_name=excluded.playlist_name,
                        track_name=excluded.track_name,
                        artist_names=excluded.artist_names,
                        source_song_ids=excluded.source_song_ids,
                        raw_json=excluded.raw_json,
                        updated_at=excluded.updated_at
                    """,
                    (
                        playlist_url,
                        playlist_name,
                        track["track_name"],
                        track["track_url"],
                        track["artist_names"],
                        source_song_ids,
                        track["raw_json"],
                        now(),
                        now(),
                    ),
                )
                summary["playlist_track_rows_upserted"] += max(0, cur.rowcount)
                for source in source_rows:
                    cur = conn.execute(
                        """
                        INSERT INTO cyanite_seed_song_playlist_tracks (
                            song_id, song_title, playlist_url, playlist_name, spotify_playlist_id,
                            track_position, spotify_track_id, track_name, artist_names, album_name,
                            album_release_date, isrc, popularity, duration_ms, explicit, track_url,
                            raw_json, fetched_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(song_id, playlist_url, track_url) DO UPDATE SET
                            song_title=excluded.song_title,
                            playlist_name=excluded.playlist_name,
                            spotify_playlist_id=excluded.spotify_playlist_id,
                            track_position=excluded.track_position,
                            spotify_track_id=excluded.spotify_track_id,
                            track_name=excluded.track_name,
                            artist_names=excluded.artist_names,
                            album_name=excluded.album_name,
                            album_release_date=excluded.album_release_date,
                            isrc=excluded.isrc,
                            popularity=excluded.popularity,
                            duration_ms=excluded.duration_ms,
                            explicit=excluded.explicit,
                            raw_json=excluded.raw_json,
                            fetched_at=excluded.fetched_at,
                            updated_at=excluded.updated_at
                        """,
                        (
                            int(source["song_id"]),
                            source["song_title"],
                            playlist_url,
                            playlist_name,
                            spotify_playlist_id,
                            track["track_position"],
                            track["spotify_track_id"],
                            track["track_name"],
                            track["artist_names"],
                            track["album_name"],
                            track["album_release_date"],
                            track["isrc"],
                            track["popularity"],
                            track["duration_ms"],
                            track["explicit"],
                            track["track_url"],
                            track["raw_json"],
                            imported_at,
                            imported_at,
                        ),
                    )
                    summary["song_track_rows_upserted"] += max(0, cur.rowcount)

        for playlist_url, track_count in playlist_track_counts.items():
            source_rows = [
                item
                for matches in seed_by_name.values()
                for item in matches
                if item["playlist_url"] == playlist_url
            ]
            if not source_rows:
                continue
            playlist_name = source_rows[0].get("playlist_name") or ""
            source_song_ids = ",".join(sorted({str(int(item["song_id"] or 0)) for item in source_rows}, key=int))
            spotify_playlist_id = source_rows[0].get("spotify_playlist_id") or ""
            cur = conn.execute(
                """
                INSERT INTO cyanite_seed_playlist_track_harvest_runs (
                    playlist_url, spotify_playlist_id, playlist_name, source_song_ids,
                    status, request_count, track_count, mapped_row_count, error,
                    started_at, completed_at, updated_at
                ) VALUES (?, ?, ?, ?, 'completed_from_tunemymusic_csv', 0, ?, ?, '', ?, ?, ?)
                ON CONFLICT(playlist_url) DO UPDATE SET
                    spotify_playlist_id=excluded.spotify_playlist_id,
                    playlist_name=excluded.playlist_name,
                    source_song_ids=excluded.source_song_ids,
                    status=excluded.status,
                    request_count=excluded.request_count,
                    track_count=excluded.track_count,
                    mapped_row_count=excluded.mapped_row_count,
                    error=excluded.error,
                    completed_at=excluded.completed_at,
                    updated_at=excluded.updated_at
                """,
                (
                    playlist_url,
                    spotify_playlist_id,
                    playlist_name,
                    source_song_ids,
                    int(track_count),
                    int(track_count * max(1, len(source_rows))),
                    imported_at,
                    imported_at,
                    imported_at,
                ),
            )
            summary["playlist_runs_marked"] += max(0, cur.rowcount)

        conn.commit()

    with connect(DB_PATH) as conn:
        summary["distinct_tracks"] = conn.execute(
            """
            SELECT COUNT(DISTINCT spotify_track_id)
            FROM cyanite_seed_song_playlist_tracks
            WHERE COALESCE(spotify_track_id, '') != ''
            """
        ).fetchone()[0]
        summary["distinct_artists"] = conn.execute(
            """
            SELECT COUNT(DISTINCT artist_names)
            FROM cyanite_seed_song_playlist_tracks
            WHERE COALESCE(artist_names, '') != ''
            """
        ).fetchone()[0]

    summary["matched_playlist_names"] = len(matched_names)
    summary["unmatched_playlist_names"] = sorted(unmatched_names)
    summary["ambiguous_playlist_names"] = dict(sorted(ambiguous_names.items()))
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("csv_path", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    init_db(DB_PATH)
    ensure_tables()
    summary = import_csv(args.csv_path, dry_run=args.dry_run)
    local_data_path("tunemymusic_cyanite_tracks_import_report.json").write_text(
        json.dumps(summary, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2))
    return 0 if summary.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
