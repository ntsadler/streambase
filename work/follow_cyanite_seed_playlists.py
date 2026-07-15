#!/usr/bin/env python3
"""Follow Cyanite seed playlists on the configured Spotify user account."""

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

from src.database import connect, init_db  # noqa: E402
from src.settings import DB_PATH, local_data_path  # noqa: E402
from src.spotify_api import API_BASE, SpotifyAPI, extract_playlist_id  # noqa: E402


SOURCE = "cyanite_seed"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class MinuteLimiter:
    def __init__(self, requests_per_minute: float) -> None:
        self.interval = 60.0 / max(float(requests_per_minute or 1), 0.01)
        self.last_request_at = 0.0

    def wait(self) -> None:
        if not self.last_request_at:
            return
        remaining = self.interval - (time.monotonic() - self.last_request_at)
        if remaining > 0:
            time.sleep(remaining)

    def mark(self) -> None:
        self.last_request_at = time.monotonic()


def ensure_tables() -> None:
    with connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS spotify_playlist_follow_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                playlist_url TEXT UNIQUE,
                spotify_playlist_id TEXT,
                playlist_name TEXT,
                source_song_ids TEXT,
                status TEXT DEFAULT 'planned',
                public_follow INTEGER DEFAULT 0,
                request_count INTEGER DEFAULT 0,
                error TEXT,
                followed_at TEXT,
                updated_at TEXT
            )
            """
        )
        conn.commit()


def load_targets(limit: int = 0, force: bool = False) -> list[dict]:
    status_filter = "" if force else "AND coalesce(r.status, '') != 'followed'"
    sql = f"""
        WITH target_rows AS (
            SELECT
                spt.playlist_url,
                max(spt.playlist_name) AS playlist_name,
                group_concat(DISTINCT spt.song_id) AS source_song_ids
            FROM song_playlist_targets spt
            WHERE spt.source = ?
              AND coalesce(spt.playlist_url, '') != ''
            GROUP BY spt.playlist_url
        )
        SELECT t.*
        FROM target_rows t
        LEFT JOIN spotify_playlist_follow_runs r
          ON r.playlist_url = t.playlist_url
        WHERE 1=1 {status_filter}
        ORDER BY t.source_song_ids, t.playlist_name, t.playlist_url
    """
    if limit:
        sql += f" LIMIT {int(limit)}"
    with connect(DB_PATH) as conn:
        return [dict(row) for row in conn.execute(sql, (SOURCE,)).fetchall()]


def mark_run(playlist: dict, status: str, **fields) -> None:
    playlist_id = fields.get("spotify_playlist_id") or extract_playlist_id(playlist["playlist_url"])
    with connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO spotify_playlist_follow_runs (
                playlist_url, spotify_playlist_id, playlist_name, source_song_ids,
                status, public_follow, request_count, error, followed_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(playlist_url) DO UPDATE SET
                spotify_playlist_id=excluded.spotify_playlist_id,
                playlist_name=excluded.playlist_name,
                source_song_ids=excluded.source_song_ids,
                status=excluded.status,
                public_follow=excluded.public_follow,
                request_count=excluded.request_count,
                error=excluded.error,
                followed_at=coalesce(spotify_playlist_follow_runs.followed_at, excluded.followed_at),
                updated_at=excluded.updated_at
            """,
            (
                playlist["playlist_url"],
                playlist_id,
                playlist.get("playlist_name") or "",
                playlist.get("source_song_ids") or "",
                status,
                1 if fields.get("public_follow") else 0,
                int(fields.get("request_count") or 0),
                fields.get("error") or "",
                fields.get("followed_at"),
                utc_now(),
            ),
        )
        conn.commit()


def follow_playlist(client: SpotifyAPI, limiter: MinuteLimiter, playlist: dict, public_follow: bool) -> dict:
    playlist_id = extract_playlist_id(playlist["playlist_url"])
    if not playlist_id:
        raise RuntimeError("Could not parse Spotify playlist id")
    resp = None
    for attempt in range(2):
        limiter.wait()
        resp = requests.put(
            f"{API_BASE}/playlists/{playlist_id}/followers",
            headers={**client._headers(user=True), "Content-Type": "application/json"},
            data=json.dumps({"public": bool(public_follow)}),
            timeout=client.timeout,
        )
        limiter.mark()
        if resp.status_code != 401 or attempt:
            break
        client._user_token = ""
    if resp.status_code == 429:
        retry_after = int(resp.headers.get("Retry-After") or 3600)
        raise RuntimeError(f"Spotify 429 rate limit; retry after {retry_after} seconds")
    if resp.status_code in {200, 201, 204}:
        return {"request_count": 1, "spotify_playlist_id": playlist_id}
    detail = resp.text[:500]
    raise RuntimeError(f"Spotify follow failed HTTP {resp.status_code}: {detail}")


def stats() -> dict:
    with connect(DB_PATH) as conn:
        return {
            "total_targets": conn.execute(
                "SELECT COUNT(DISTINCT playlist_url) FROM song_playlist_targets WHERE source=? AND coalesce(playlist_url,'')!=''",
                (SOURCE,),
            ).fetchone()[0],
            "followed": conn.execute("SELECT COUNT(*) FROM spotify_playlist_follow_runs WHERE status='followed'").fetchone()[0],
            "failed": conn.execute("SELECT COUNT(*) FROM spotify_playlist_follow_runs WHERE status='failed'").fetchone()[0],
            "rate_limited": conn.execute("SELECT COUNT(*) FROM spotify_playlist_follow_runs WHERE status='rate_limited'").fetchone()[0],
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--requests-per-minute", type=float, default=1.0)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--public", action="store_true", help="Show followed playlists publicly on the Spotify profile.")
    args = parser.parse_args()

    init_db(DB_PATH)
    ensure_tables()
    client = SpotifyAPI(timeout=20)
    if not client.user_configured:
        raise SystemExit("Spotify user authorization is not configured.")
    limiter = MinuteLimiter(args.requests_per_minute)
    targets = load_targets(limit=args.limit, force=args.force)
    log_path = local_data_path("spotify_playlist_follow_runs.jsonl")
    start_event = {"event": "started", "targets": len(targets), "requests_per_minute": args.requests_per_minute, "public": bool(args.public)}
    log_path.open("a", encoding="utf-8").write(json.dumps({**start_event, "at": utc_now()}, sort_keys=True) + "\n")
    print(json.dumps(start_event), flush=True)

    totals = {"followed": 0, "failed": 0, "requests": 0}
    for index, playlist in enumerate(targets, start=1):
        try:
            result = follow_playlist(client, limiter, playlist, public_follow=args.public)
            mark_run(
                playlist,
                "followed",
                spotify_playlist_id=result["spotify_playlist_id"],
                public_follow=args.public,
                request_count=result["request_count"],
                followed_at=utc_now(),
            )
            totals["followed"] += 1
            totals["requests"] += result["request_count"]
            event = {"event": "followed", "index": index, "target_count": len(targets), **playlist, **result, "stats": stats()}
        except Exception as exc:
            message = str(exc)
            status = "rate_limited" if "429" in message else "failed"
            mark_run(playlist, status, error=message, request_count=1 if "HTTP" in message or "429" in message else 0)
            totals["failed"] += 1
            event = {"event": status, "index": index, "target_count": len(targets), **playlist, "error": message, "stats": stats()}
            log_path.open("a", encoding="utf-8").write(json.dumps({**event, "at": utc_now()}, sort_keys=True) + "\n")
            print(json.dumps(event), flush=True)
            if status == "rate_limited" or "insufficient" in message.lower() or "scope" in message.lower() or "403" in message:
                break
            continue
        log_path.open("a", encoding="utf-8").write(json.dumps({**event, "at": utc_now()}, sort_keys=True) + "\n")
        print(json.dumps(event), flush=True)

    stopped = {"event": "stopped", "totals": totals, "stats": stats()}
    log_path.open("a", encoding="utf-8").write(json.dumps({**stopped, "at": utc_now()}, sort_keys=True) + "\n")
    print(json.dumps(stopped, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
