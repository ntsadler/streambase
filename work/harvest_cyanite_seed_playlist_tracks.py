#!/usr/bin/env python3
"""Slowly harvest full Spotify tracklists for Cyanite seed playlists."""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.database import connect, init_db, now  # noqa: E402
from src.settings import DB_PATH, local_data_path  # noqa: E402
from src.spotify_api import API_BASE, SpotifyAPI, extract_playlist_id  # noqa: E402


SOURCE = "cyanite_seed"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class SpotifyMinuteLimiter:
    def __init__(self, requests_per_minute: float) -> None:
        self.interval = 60.0 / max(float(requests_per_minute or 1), 0.01)
        self.last_request_at = 0.0

    def wait(self) -> None:
        elapsed = time.monotonic() - self.last_request_at
        remaining = self.interval - elapsed
        if self.last_request_at and remaining > 0:
            time.sleep(remaining)

    def mark(self) -> None:
        self.last_request_at = time.monotonic()


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


def load_playlist_targets(limit: int = 0, force: bool = False) -> list[dict]:
    status_filter = "" if force else "AND coalesce(r.status, '') NOT IN ('completed', 'api_forbidden', 'unavailable', 'failed')"
    sql = f"""
        WITH target_rows AS (
            SELECT
                spt.playlist_url,
                max(spt.playlist_name) AS playlist_name,
                group_concat(DISTINCT spt.song_id) AS source_song_ids,
                group_concat(DISTINCT coalesce(s.title, spt.song_id)) AS source_song_titles
            FROM song_playlist_targets spt
            LEFT JOIN songs s ON s.id = spt.song_id
            WHERE spt.source = ?
              AND coalesce(spt.playlist_url, '') != ''
            GROUP BY spt.playlist_url
        )
        SELECT t.*
        FROM target_rows t
        LEFT JOIN cyanite_seed_playlist_track_harvest_runs r
          ON r.playlist_url = t.playlist_url
        WHERE 1=1 {status_filter}
        ORDER BY t.source_song_ids, t.playlist_name, t.playlist_url
    """
    if limit:
        sql += f" LIMIT {int(limit)}"
    with connect(DB_PATH) as conn:
        return [dict(row) for row in conn.execute(sql, (SOURCE,)).fetchall()]


def source_song_rows(playlist_url: str) -> list[dict]:
    with connect(DB_PATH) as conn:
        return [
            dict(row)
            for row in conn.execute(
                """
                SELECT DISTINCT spt.song_id, coalesce(s.title, '') AS song_title
                FROM song_playlist_targets spt
                LEFT JOIN songs s ON s.id = spt.song_id
                WHERE spt.source = ? AND spt.playlist_url = ?
                ORDER BY spt.song_id
                """,
                (SOURCE, playlist_url),
            ).fetchall()
        ]


def mark_run(playlist: dict, status: str, **fields) -> None:
    payload = {
        "spotify_playlist_id": fields.get("spotify_playlist_id") or extract_playlist_id(playlist["playlist_url"]),
        "playlist_name": playlist.get("playlist_name") or "",
        "source_song_ids": playlist.get("source_song_ids") or "",
        "status": status,
        "request_count": int(fields.get("request_count") or 0),
        "track_count": int(fields.get("track_count") or 0),
        "mapped_row_count": int(fields.get("mapped_row_count") or 0),
        "error": fields.get("error") or "",
        "started_at": fields.get("started_at"),
        "completed_at": fields.get("completed_at"),
        "updated_at": utc_now(),
    }
    with connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO cyanite_seed_playlist_track_harvest_runs (
                playlist_url, spotify_playlist_id, playlist_name, source_song_ids,
                status, request_count, track_count, mapped_row_count, error,
                started_at, completed_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(playlist_url) DO UPDATE SET
                spotify_playlist_id=excluded.spotify_playlist_id,
                playlist_name=excluded.playlist_name,
                source_song_ids=excluded.source_song_ids,
                status=excluded.status,
                request_count=excluded.request_count,
                track_count=excluded.track_count,
                mapped_row_count=excluded.mapped_row_count,
                error=excluded.error,
                started_at=coalesce(cyanite_seed_playlist_track_harvest_runs.started_at, excluded.started_at),
                completed_at=excluded.completed_at,
                updated_at=excluded.updated_at
            """,
            (
                playlist["playlist_url"],
                payload["spotify_playlist_id"],
                payload["playlist_name"],
                payload["source_song_ids"],
                payload["status"],
                payload["request_count"],
                payload["track_count"],
                payload["mapped_row_count"],
                payload["error"],
                payload["started_at"],
                payload["completed_at"],
                payload["updated_at"],
            ),
        )
        conn.commit()


def fetch_track_page(client: SpotifyAPI, limiter: SpotifyMinuteLimiter, playlist_id: str, offset: int) -> dict:
    limiter.wait()
    resp = requests.get(
        f"{API_BASE}/playlists/{playlist_id}/tracks",
        headers=client._headers(user=client.user_configured),
        params={
            "fields": (
                "items(added_at,track(id,name,artists(name,id),album(name,release_date),"
                "external_ids(isrc),external_urls,duration_ms,explicit,popularity)),next,total"
            ),
            "limit": 100,
            "offset": int(offset),
        },
        timeout=client.timeout,
    )
    limiter.mark()
    if resp.status_code == 429:
        retry_after = int(resp.headers.get("Retry-After") or 3600)
        raise RuntimeError(f"Spotify 429 rate limit; retry after {retry_after} seconds")
    if resp.status_code == 403:
        raise RuntimeError("Spotify 403 forbidden/unavailable playlist")
    if resp.status_code == 404:
        raise RuntimeError("Spotify 404 unavailable playlist")
    resp.raise_for_status()
    return resp.json()


def normalize_track_item(item: dict, position: int) -> dict:
    track = item.get("track") or {}
    album = track.get("album") or {}
    external_ids = track.get("external_ids") or {}
    external_urls = track.get("external_urls") or {}
    return {
        "track_position": position,
        "spotify_track_id": track.get("id") or "",
        "track_name": track.get("name") or "",
        "artist_names": "; ".join(a.get("name") or "" for a in track.get("artists") or [] if a.get("name")),
        "album_name": album.get("name") or "",
        "album_release_date": album.get("release_date") or "",
        "isrc": external_ids.get("isrc") or "",
        "popularity": int(track.get("popularity") or 0),
        "duration_ms": int(track.get("duration_ms") or 0),
        "explicit": 1 if track.get("explicit") else 0,
        "track_url": external_urls.get("spotify") or (f"https://open.spotify.com/track/{track.get('id')}" if track.get("id") else ""),
        "raw_json": json.dumps(item, ensure_ascii=True),
    }


def save_tracks_for_playlist(playlist: dict, spotify_playlist_id: str, tracks: list[dict]) -> int:
    song_rows = source_song_rows(playlist["playlist_url"])
    fetched_at = utc_now()
    mapped = 0
    with connect(DB_PATH) as conn:
        for track in tracks:
            if not track.get("track_url"):
                continue
            conn.execute(
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
                    playlist["playlist_url"],
                    playlist.get("playlist_name") or "",
                    track["track_name"],
                    track["track_url"],
                    track["artist_names"],
                    playlist.get("source_song_ids") or "",
                    track["raw_json"],
                    now(),
                    now(),
                ),
            )
            for song in song_rows:
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
                        int(song["song_id"]),
                        song["song_title"],
                        playlist["playlist_url"],
                        playlist.get("playlist_name") or "",
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
                        fetched_at,
                        fetched_at,
                    ),
                )
                mapped += max(0, cur.rowcount)
        conn.commit()
    return mapped


def harvest_playlist(client: SpotifyAPI, limiter: SpotifyMinuteLimiter, playlist: dict) -> dict:
    playlist_id = extract_playlist_id(playlist["playlist_url"])
    if not playlist_id:
        raise RuntimeError("Could not parse Spotify playlist id")
    offset = 0
    request_count = 0
    tracks: list[dict] = []
    while True:
        page = fetch_track_page(client, limiter, playlist_id, offset)
        request_count += 1
        items = page.get("items") or []
        for index, item in enumerate(items, start=offset + 1):
            normalized = normalize_track_item(item, index)
            if normalized.get("track_url"):
                tracks.append(normalized)
        if not page.get("next") or not items:
            break
        offset += 100
    mapped = save_tracks_for_playlist(playlist, playlist_id, tracks)
    return {"request_count": request_count, "track_count": len(tracks), "mapped_row_count": mapped}


def stats() -> dict:
    with connect(DB_PATH) as conn:
        return {
            "playlist_runs": conn.execute("SELECT COUNT(*) FROM cyanite_seed_playlist_track_harvest_runs").fetchone()[0],
            "completed_playlists": conn.execute(
                "SELECT COUNT(*) FROM cyanite_seed_playlist_track_harvest_runs WHERE status='completed'"
            ).fetchone()[0],
            "track_rows": conn.execute("SELECT COUNT(*) FROM cyanite_seed_song_playlist_tracks").fetchone()[0],
            "distinct_tracks": conn.execute(
                "SELECT COUNT(DISTINCT spotify_track_id) FROM cyanite_seed_song_playlist_tracks WHERE coalesce(spotify_track_id,'')!=''"
            ).fetchone()[0],
            "distinct_artists": conn.execute(
                """
                SELECT COUNT(DISTINCT trim(value))
                FROM cyanite_seed_song_playlist_tracks,
                     json_each('["' || replace(replace(artist_names, '"', ''), '; ', '","') || '"]')
                WHERE trim(value) != ''
                """
            ).fetchone()[0],
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--requests-per-minute", type=float, default=1.0)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    init_db(DB_PATH)
    ensure_tables()
    client = SpotifyAPI(timeout=20)
    if not client.configured:
        raise SystemExit("Spotify API credentials are not configured.")
    limiter = SpotifyMinuteLimiter(args.requests_per_minute)
    log_path = local_data_path("cyanite_seed_track_harvest.jsonl")
    targets = load_playlist_targets(limit=args.limit, force=args.force)
    started = utc_now()
    summary = {"event": "started", "started": started, "targets": len(targets), "requests_per_minute": args.requests_per_minute}
    log_path.open("a", encoding="utf-8").write(json.dumps(summary, sort_keys=True) + "\n")
    print(json.dumps(summary), flush=True)

    totals = {"playlists": 0, "requests": 0, "tracks": 0, "mapped_rows": 0, "errors": 0}
    for index, playlist in enumerate(targets, start=1):
        mark_run(playlist, "running", started_at=utc_now())
        try:
            result = harvest_playlist(client, limiter, playlist)
            mark_run(
                playlist,
                "completed",
                spotify_playlist_id=extract_playlist_id(playlist["playlist_url"]),
                request_count=result["request_count"],
                track_count=result["track_count"],
                mapped_row_count=result["mapped_row_count"],
                completed_at=utc_now(),
            )
            totals["playlists"] += 1
            totals["requests"] += result["request_count"]
            totals["tracks"] += result["track_count"]
            totals["mapped_rows"] += result["mapped_row_count"]
            event = {"event": "playlist_completed", "index": index, "target_count": len(targets), **playlist, **result, "stats": stats()}
        except Exception as exc:
            message = str(exc)
            totals["errors"] += 1
            if "429" in message:
                status = "rate_limited"
            elif "403" in message:
                status = "api_forbidden"
            elif "404" in message or "unavailable" in message.lower():
                status = "unavailable"
            else:
                status = "failed"
            mark_run(playlist, status, error=message)
            event = {"event": "playlist_error", "index": index, "target_count": len(targets), **playlist, "error": message, "stats": stats()}
            if "429" in message:
                log_path.open("a", encoding="utf-8").write(json.dumps(event, sort_keys=True) + "\n")
                print(json.dumps(event), flush=True)
                break
        log_path.open("a", encoding="utf-8").write(json.dumps(event, sort_keys=True) + "\n")
        print(json.dumps(event), flush=True)

    stopped = {"event": "stopped", "totals": totals, "stats": stats()}
    log_path.open("a", encoding="utf-8").write(json.dumps(stopped, sort_keys=True) + "\n")
    print(json.dumps(stopped, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
