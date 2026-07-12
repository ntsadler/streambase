#!/usr/bin/env python3
"""Harvest Cyanite seed playlist tracks and enrich their artists with Viberate."""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.database import connect, init_db, now, upsert_artist_reference, upsert_playlist  # noqa: E402
from src.settings import DB_PATH, local_data_path  # noqa: E402
from src.spotify_api import SpotifyAPI  # noqa: E402
from src.viberate import ViberateAPI  # noqa: E402
from src.viberate_mining import _viberate_sleep_seconds  # noqa: E402


def ensure_tables() -> None:
    with connect(DB_PATH) as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS cyanite_seed_playlist_tracks (
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
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS viberate_artist_enrichments (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               artist_name TEXT UNIQUE,
               matched_name TEXT,
               viberate_artist_id TEXT,
               status TEXT DEFAULT 'new',
               playlist_count INTEGER DEFAULT 0,
               track_count INTEGER DEFAULT 0,
               confidence_score REAL DEFAULT 0,
               raw_json TEXT,
               error TEXT,
               created_at TEXT,
               updated_at TEXT
            )"""
        )
        conn.commit()


def cyanite_seed_playlists(limit: int = 0) -> list[dict]:
    sql = """
        SELECT playlist_url,
               max(playlist_name) AS playlist_name,
               group_concat(DISTINCT song_id) AS source_song_ids,
               max(related_artists) AS related_artists
        FROM song_playlist_targets
        WHERE source='cyanite_seed' AND coalesce(playlist_url,'')!=''
        GROUP BY playlist_url
        ORDER BY playlist_url
    """
    if limit:
        sql += f" LIMIT {int(limit)}"
    with connect(DB_PATH) as conn:
        return [dict(row) for row in conn.execute(sql).fetchall()]


def already_harvested_urls() -> set[str]:
    with connect(DB_PATH) as conn:
        rows = conn.execute("SELECT DISTINCT playlist_url FROM cyanite_seed_playlist_tracks").fetchall()
    return {row["playlist_url"] for row in rows}


def split_artists(value: str) -> list[str]:
    artists = []
    for raw in re.split(r"[;,]", value or ""):
        name = " ".join(str(raw or "").strip().split())
        if name and name.lower() != "strange hotels" and not name.isdigit():
            artists.append(name)
    return artists


def save_tracks(playlist: dict, spotify_meta: dict) -> int:
    playlist_url = spotify_meta.get("playlist_url") or playlist.get("playlist_url") or ""
    playlist_name = spotify_meta.get("playlist_name") or playlist.get("playlist_name") or ""
    related_artists = spotify_meta.get("related_artists") or playlist.get("related_artists") or ""
    if spotify_meta:
        upsert_playlist(
            {
                "playlist_name": playlist_name,
                "playlist_url": playlist_url,
                "curator_name": spotify_meta.get("curator_name") or "Unknown Curator",
                "follower_count": spotify_meta.get("follower_count") or 0,
                "related_artists": related_artists,
                "spotify_description": spotify_meta.get("spotify_description") or "",
                "spotify_playlist_id": spotify_meta.get("spotify_playlist_id") or "",
            },
            DB_PATH,
        )
    saved = 0
    with connect(DB_PATH) as conn:
        if related_artists:
            conn.execute(
                """UPDATE song_playlist_targets
                   SET related_artists=?, updated_at=?
                   WHERE source='cyanite_seed' AND playlist_url=?""",
                (related_artists, now(), playlist_url),
            )
        for track in spotify_meta.get("spotify_tracks") or []:
            track_url = track.get("spotify_url") or ""
            if not track_url:
                continue
            cur = conn.execute(
                """INSERT INTO cyanite_seed_playlist_tracks
                   (playlist_url,playlist_name,track_name,track_url,artist_names,source_song_ids,raw_json,created_at,updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(playlist_url,track_url) DO UPDATE SET
                   playlist_name=excluded.playlist_name,
                   track_name=excluded.track_name,
                   artist_names=excluded.artist_names,
                   source_song_ids=excluded.source_song_ids,
                   raw_json=excluded.raw_json,
                   updated_at=excluded.updated_at""",
                (
                    playlist_url,
                    playlist_name,
                    track.get("name") or "",
                    track_url,
                    "; ".join(track.get("artists") or []),
                    playlist.get("source_song_ids") or "",
                    json.dumps(track, ensure_ascii=True),
                    now(),
                    now(),
                ),
            )
            saved += max(0, cur.rowcount)
        conn.commit()
    return saved


def harvest_spotify_tracks(limit: int = 0, force: bool = False) -> dict:
    spotify = SpotifyAPI()
    if not spotify.configured:
        return {"ok": False, "error": "Spotify API credentials are not configured.", "playlists": 0, "tracks": 0}
    harvested = set() if force else already_harvested_urls()
    playlists = [row for row in cyanite_seed_playlists(limit) if force or row["playlist_url"] not in harvested]
    summary = {"ok": True, "playlists": len(playlists), "spotify_enriched": 0, "tracks": 0, "errors": []}
    for index, playlist in enumerate(playlists, start=1):
        try:
            meta = spotify.normalize_playlist(playlist["playlist_url"])
            if meta:
                summary["spotify_enriched"] += 1
                summary["tracks"] += save_tracks(playlist, meta)
        except Exception as exc:
            summary["errors"].append({"playlist_url": playlist["playlist_url"], "error": str(exc)})
        if index % 25 == 0:
            print(f"spotify {index}/{len(playlists)} playlists; tracks={summary['tracks']}", flush=True)
    return summary


def artist_stats() -> dict[str, dict]:
    stats = defaultdict(lambda: {"playlist_urls": set(), "track_urls": set(), "seed_rows": 0})
    with connect(DB_PATH) as conn:
        for row in conn.execute("SELECT playlist_url, track_url, artist_names FROM cyanite_seed_playlist_tracks").fetchall():
            for artist in split_artists(row["artist_names"]):
                stats[artist]["playlist_urls"].add(row["playlist_url"])
                stats[artist]["track_urls"].add(row["track_url"])
        for row in conn.execute(
            "SELECT playlist_url, related_artists FROM song_playlist_targets WHERE source='cyanite_seed'"
        ).fetchall():
            for artist in split_artists(row["related_artists"]):
                stats[artist]["playlist_urls"].add(row["playlist_url"])
                stats[artist]["seed_rows"] += 1
    return stats


def existing_viberate_artists() -> set[str]:
    with connect(DB_PATH) as conn:
        rows = conn.execute("SELECT artist_name FROM viberate_artist_enrichments WHERE status IN ('matched','not_found')").fetchall()
    return {row["artist_name"].lower() for row in rows}


def pick_artist(raw: dict) -> dict:
    data = raw.get("data") if isinstance(raw, dict) else []
    if isinstance(data, dict):
        data = data.get("data") or data.get("items") or []
    if not isinstance(data, list) or not data:
        return {}
    return data[0] or {}


def artist_id(artist: dict) -> str:
    return str(artist.get("uuid") or artist.get("id") or artist.get("artist_id") or "")


def enrich_viberate_artists(limit: int = 0, force: bool = False, sleep_seconds: float | None = None) -> dict:
    client = ViberateAPI()
    if not client.configured:
        return {"ok": False, "error": "Viberate API key is not configured.", "artists": 0}
    sleep_for = _viberate_sleep_seconds(sleep_seconds)
    stats = artist_stats()
    done = set() if force else existing_viberate_artists()
    ranked = sorted(
        (
            (artist, len(values["playlist_urls"]), len(values["track_urls"]), values["seed_rows"])
            for artist, values in stats.items()
            if force or artist.lower() not in done
        ),
        key=lambda item: (-item[1], -item[2], item[0].lower()),
    )
    if limit:
        ranked = ranked[: int(limit)]
    summary = {"ok": True, "artists": len(ranked), "matched": 0, "not_found": 0, "errors": []}
    for index, (artist, playlist_count, track_count, seed_rows) in enumerate(ranked, start=1):
        raw = {}
        status = "not_found"
        matched_name = ""
        vb_id = ""
        error = ""
        confidence = min(98, 55 + min(30, playlist_count * 3) + min(10, track_count))
        try:
            raw = client.search_artists(artist, limit=1)
            match = pick_artist(raw)
            if match:
                status = "matched"
                matched_name = match.get("name") or artist
                vb_id = artist_id(match)
                summary["matched"] += 1
                upsert_artist_reference(
                    {
                        "artist_name": artist,
                        "source": "viberate_cyanite_playlist_artist",
                        "confidence_score": confidence,
                        "notes": json.dumps(
                            {
                                "matched_name": matched_name,
                                "viberate_artist_id": vb_id,
                                "playlist_count": playlist_count,
                                "track_count": track_count,
                                "seed_rows": seed_rows,
                            },
                            ensure_ascii=True,
                        ),
                    },
                    DB_PATH,
                )
            else:
                summary["not_found"] += 1
        except Exception as exc:
            status = "error"
            error = str(exc)
            summary["errors"].append({"artist_name": artist, "error": error})
        with connect(DB_PATH) as conn:
            conn.execute(
                """INSERT INTO viberate_artist_enrichments
                   (artist_name,matched_name,viberate_artist_id,status,playlist_count,track_count,confidence_score,raw_json,error,created_at,updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(artist_name) DO UPDATE SET
                   matched_name=excluded.matched_name,
                   viberate_artist_id=excluded.viberate_artist_id,
                   status=excluded.status,
                   playlist_count=excluded.playlist_count,
                   track_count=excluded.track_count,
                   confidence_score=excluded.confidence_score,
                   raw_json=excluded.raw_json,
                   error=excluded.error,
                   updated_at=excluded.updated_at""",
                (
                    artist,
                    matched_name,
                    vb_id,
                    status,
                    playlist_count,
                    track_count,
                    confidence,
                    json.dumps(raw, ensure_ascii=True),
                    error,
                    now(),
                    now(),
                ),
            )
            conn.commit()
        if index % 10 == 0 or status == "matched":
            print(f"viberate {index}/{len(ranked)} {status}: {artist} playlists={playlist_count}", flush=True)
        if index < len(ranked) and sleep_for:
            time.sleep(sleep_for)
    return summary


def write_report(summary: dict) -> None:
    stats = artist_stats()
    top_artists = [
        {"artist_name": artist, "playlist_count": len(values["playlist_urls"]), "track_count": len(values["track_urls"])}
        for artist, _count in Counter({k: len(v["playlist_urls"]) for k, v in stats.items()}).most_common(50)
        for values in [stats[artist]]
    ]
    with connect(DB_PATH) as conn:
        rows = conn.execute(
            "SELECT status, COUNT(*) AS count FROM viberate_artist_enrichments GROUP BY status"
        ).fetchall()
    report = {**summary, "top_artists": top_artists, "viberate_status_counts": [dict(row) for row in rows]}
    local_data_path("cyanite_playlist_viberate_artist_enrichment.json").write_text(
        json.dumps(report, indent=2),
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--playlist-limit", type=int, default=0)
    parser.add_argument("--artist-limit", type=int, default=0)
    parser.add_argument("--skip-spotify", action="store_true")
    parser.add_argument("--skip-viberate", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--sleep-seconds", type=float, default=None)
    args = parser.parse_args()

    init_db(DB_PATH)
    ensure_tables()
    summary = {"spotify": {}, "viberate": {}}
    if not args.skip_spotify:
        summary["spotify"] = harvest_spotify_tracks(args.playlist_limit, args.force)
    if not args.skip_viberate:
        for artist, values in artist_stats().items():
            upsert_artist_reference(
                {
                    "artist_name": artist,
                    "source": "cyanite_playlist_artist",
                    "confidence_score": min(95, 45 + len(values["playlist_urls"]) * 4 + min(10, len(values["track_urls"]))),
                    "notes": json.dumps(
                        {
                            "playlist_count": len(values["playlist_urls"]),
                            "track_count": len(values["track_urls"]),
                            "source": "cyanite_seed_playlist_tracks",
                        },
                        ensure_ascii=True,
                    ),
                },
                DB_PATH,
            )
        summary["viberate"] = enrich_viberate_artists(args.artist_limit, args.force, args.sleep_seconds)
    write_report(summary)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
