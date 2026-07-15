#!/usr/bin/env python3
"""Build ranked track anchors from imported Cyanite seed playlist tracks."""

from __future__ import annotations

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

from src.database import connect, init_db  # noqa: E402
from src.settings import DB_PATH, local_data_path  # noqa: E402


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFKC", value or "").strip().lower()
    return re.sub(r"\s+", " ", value)


def reference_key(row: dict) -> str:
    spotify_track_id = (row.get("spotify_track_id") or "").strip()
    if spotify_track_id:
        return f"spotify:{spotify_track_id}"
    isrc = (row.get("isrc") or "").strip()
    if isrc:
        return f"isrc:{isrc}"
    return f"text:{normalize(row.get('track_name') or '')}|{normalize(row.get('artist_names') or '')}"


def ensure_table() -> None:
    with connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS cyanite_track_mining_references (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                reference_key TEXT UNIQUE,
                spotify_track_id TEXT,
                isrc TEXT,
                track_name TEXT,
                artist_names TEXT,
                album_name TEXT,
                root_song_count INTEGER DEFAULT 0,
                playlist_count INTEGER DEFAULT 0,
                occurrence_count INTEGER DEFAULT 0,
                root_song_ids TEXT,
                root_song_titles TEXT,
                playlist_urls_json TEXT,
                playlist_names_json TEXT,
                mining_weight REAL DEFAULT 0,
                updated_at TEXT
            )
            """
        )
        conn.commit()


def build() -> dict:
    ensure_table()
    with connect(DB_PATH) as conn:
        rows = [
            dict(row)
            for row in conn.execute(
                """
                SELECT song_id, song_title, playlist_url, playlist_name,
                       spotify_track_id, track_name, artist_names, album_name, isrc
                FROM cyanite_seed_song_playlist_tracks
                WHERE COALESCE(track_name, '') != ''
                  AND COALESCE(artist_names, '') != ''
                """
            ).fetchall()
        ]

    grouped: dict[str, dict] = {}
    for row in rows:
        key = reference_key(row)
        item = grouped.setdefault(
            key,
            {
                "reference_key": key,
                "spotify_track_id": row.get("spotify_track_id") or "",
                "isrc": row.get("isrc") or "",
                "track_name": row.get("track_name") or "",
                "artist_names": row.get("artist_names") or "",
                "album_name": row.get("album_name") or "",
                "root_song_ids": set(),
                "root_song_titles": set(),
                "playlist_urls": set(),
                "playlist_names": set(),
                "occurrence_count": 0,
            },
        )
        item["occurrence_count"] += 1
        item["root_song_ids"].add(str(int(row.get("song_id") or 0)))
        if row.get("song_title"):
            item["root_song_titles"].add(row["song_title"])
        if row.get("playlist_url"):
            item["playlist_urls"].add(row["playlist_url"])
        if row.get("playlist_name"):
            item["playlist_names"].add(row["playlist_name"])

    updated_at = utc_now()
    with connect(DB_PATH) as conn:
        conn.execute("DELETE FROM cyanite_track_mining_references")
        for item in grouped.values():
            root_song_count = len(item["root_song_ids"])
            playlist_count = len(item["playlist_urls"])
            occurrence_count = int(item["occurrence_count"])
            mining_weight = root_song_count * 10 + playlist_count * 2 + min(occurrence_count, 20) * 0.5
            conn.execute(
                """
                INSERT INTO cyanite_track_mining_references (
                    reference_key, spotify_track_id, isrc, track_name, artist_names, album_name,
                    root_song_count, playlist_count, occurrence_count, root_song_ids,
                    root_song_titles, playlist_urls_json, playlist_names_json, mining_weight,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item["reference_key"],
                    item["spotify_track_id"],
                    item["isrc"],
                    item["track_name"],
                    item["artist_names"],
                    item["album_name"],
                    root_song_count,
                    playlist_count,
                    occurrence_count,
                    ",".join(sorted(item["root_song_ids"], key=int)),
                    " | ".join(sorted(item["root_song_titles"])),
                    json.dumps(sorted(item["playlist_urls"]), ensure_ascii=True),
                    json.dumps(sorted(item["playlist_names"]), ensure_ascii=True),
                    mining_weight,
                    updated_at,
                ),
            )
        conn.commit()

    summary = {
        "ok": True,
        "raw_song_playlist_track_rows": len(rows),
        "reference_tracks": len(grouped),
        "multi_root_tracks": sum(1 for item in grouped.values() if len(item["root_song_ids"]) > 1),
        "multi_playlist_tracks": sum(1 for item in grouped.values() if len(item["playlist_urls"]) > 1),
    }
    with connect(DB_PATH) as conn:
        top = [
            dict(row)
            for row in conn.execute(
                """
                SELECT track_name, artist_names, root_song_count, playlist_count, occurrence_count, mining_weight
                FROM cyanite_track_mining_references
                ORDER BY mining_weight DESC, playlist_count DESC, track_name
                LIMIT 20
                """
            ).fetchall()
        ]
    summary["top_examples"] = top
    return summary


def main() -> int:
    init_db(DB_PATH)
    summary = build()
    local_data_path("cyanite_track_mining_reference_report.json").write_text(
        json.dumps(summary, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
