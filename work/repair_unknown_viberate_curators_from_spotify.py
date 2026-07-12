#!/usr/bin/env python3
"""Repair saved Viberate playlists whose curator is still Unknown Curator."""
import argparse
import json
import sys
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import requests

from src.database import connect, get_or_create_curator, init_db, now
from src.settings import DB_PATH, local_data_path
from src.spotify_api import SpotifyAPI


def state_path():
    return local_data_path("spotify_curator_repair_state.json")


def read_state():
    path = state_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def write_state(payload):
    state_path().write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def iso_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def retry_after_seconds(exc, default=900):
    response = getattr(exc, "response", None)
    if response is None:
        return int(default)
    value = (response.headers or {}).get("Retry-After", "")
    if not value:
        return int(default)
    try:
        return max(60, int(float(value)))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(value)
            return max(60, int(parsed.timestamp() - time.time()))
        except Exception:
            return int(default)


def init_repair_table(db_path=DB_PATH):
    with connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS spotify_curator_repair_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                playlist_url TEXT UNIQUE,
                playlist_name TEXT,
                status TEXT,
                curator_name TEXT,
                error TEXT,
                attempted_at TEXT,
                updated_at TEXT
            )
            """
        )
        conn.commit()


def save_repair_run(row, status, curator_name="", error="", db_path=DB_PATH):
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO spotify_curator_repair_runs (
                playlist_url, playlist_name, status, curator_name, error, attempted_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(playlist_url) DO UPDATE SET
                playlist_name=excluded.playlist_name,
                status=excluded.status,
                curator_name=excluded.curator_name,
                error=excluded.error,
                attempted_at=excluded.attempted_at,
                updated_at=excluded.updated_at
            """,
            (
                row.get("url") or "",
                row.get("name") or "",
                status,
                curator_name or "",
                str(error or "")[:1000],
                now(),
                now(),
            ),
        )
        conn.commit()


def candidate_rows(limit: int, retry_failed=False, db_path=DB_PATH):
    sql = """
        WITH viberate_urls AS (
            SELECT DISTINCT playlist_url
            FROM song_playlist_targets
            WHERE source LIKE 'viberate%'
              AND COALESCE(playlist_url, '') != ''
            UNION
            SELECT DISTINCT playlist_url
            FROM viberate_cyanite_playlist_matches
            WHERE COALESCE(playlist_url, '') != ''
        )
        SELECT p.id, p.name, p.url, p.followers, p.spotify_playlist_id
        FROM playlists p
        JOIN viberate_urls vu ON vu.playlist_url = p.url
        LEFT JOIN curators c ON c.id = p.curator_id
        LEFT JOIN spotify_curator_repair_runs rr ON rr.playlist_url = p.url
        WHERE LOWER(COALESCE(c.name, '')) IN ('unknown curator', '')
          AND (? OR rr.playlist_url IS NULL OR rr.status = 'retry')
          AND p.url NOT LIKE 'https://open.spotify.com/playlist/37i9dQZF%'
        ORDER BY COALESCE(p.followers, 0) DESC, p.id ASC
    """
    args = (1 if retry_failed else 0,)
    if limit:
        sql += " LIMIT ?"
        args = (*args, int(limit))
    with connect(db_path) as conn:
        return [dict(row) for row in conn.execute(sql, args).fetchall()]


def apply_spotify_metadata(row, metadata, db_path=DB_PATH):
    curator_name = (metadata.get("curator_name") or "").strip()
    if not curator_name:
        return {"updated": False, "reason": "spotify_owner_blank"}
    curator_id = get_or_create_curator(curator_name, db_path)
    with connect(db_path) as conn:
        conn.execute(
            """
            UPDATE playlists
            SET curator_id = ?,
                name = COALESCE(NULLIF(?, ''), name),
                followers = CASE WHEN COALESCE(?, 0) > 0 THEN ? ELSE followers END,
                spotify_description = COALESCE(NULLIF(?, ''), spotify_description),
                spotify_playlist_id = COALESCE(NULLIF(?, ''), spotify_playlist_id)
            WHERE id = ?
            """,
            (
                curator_id,
                metadata.get("playlist_name") or "",
                int(metadata.get("follower_count") or 0),
                int(metadata.get("follower_count") or 0),
                metadata.get("spotify_description") or "",
                metadata.get("spotify_playlist_id") or "",
                int(row["id"]),
            ),
        )
        conn.execute(
            """
            UPDATE mined_playlists
            SET curator_name = ?
            WHERE playlist_url = ?
              AND LOWER(COALESCE(curator_name, '')) IN ('', 'unknown curator')
            """,
            (curator_name, row["url"]),
        )
        conn.execute(
            """
            UPDATE viberate_cyanite_playlist_matches
            SET curator_name = ?, updated_at = ?
            WHERE playlist_url = ?
              AND LOWER(COALESCE(curator_name, '')) IN ('', 'unknown curator')
            """,
            (curator_name, now(), row["url"]),
        )
        conn.commit()
    return {"updated": True, "curator_name": curator_name, "curator_id": curator_id}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--requests-per-minute", type=int, default=120)
    parser.add_argument(
        "--sleep",
        type=float,
        default=None,
        help="Deprecated. Use --requests-per-minute; if set, this exact per-request sleep is used.",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--retry-failed", action="store_true")
    parser.add_argument("--rate-limit-sleep-seconds", type=int, default=900)
    parser.add_argument("--ignore-backoff", action="store_true")
    args = parser.parse_args()

    init_db(DB_PATH)
    init_repair_table(DB_PATH)
    state = read_state()
    backoff_until = state.get("backoff_until_epoch")
    if backoff_until and not args.ignore_backoff:
        remaining = int(float(backoff_until) - time.time())
        if remaining > 0:
            print(
                json.dumps(
                    {
                        "ok": True,
                        "requested_limit": int(args.limit or 0),
                        "requests_per_minute": int(args.requests_per_minute or 120),
                        "candidate_count": 0,
                        "updated": 0,
                        "skipped": 0,
                        "rate_limited": 1,
                        "retry_after_seconds": remaining,
                        "backoff_until": state.get("backoff_until"),
                        "errors": [],
                        "examples": [],
                    },
                    indent=2,
                )
            )
            return
    spotify = SpotifyAPI(timeout=20)
    if not spotify.configured:
        raise SystemExit("Spotify credentials are not configured.")

    rows = candidate_rows(args.limit, retry_failed=args.retry_failed, db_path=DB_PATH)
    min_interval = float(args.sleep) if args.sleep is not None else 60.0 / max(1, int(args.requests_per_minute or 120))
    report = {
        "ok": True,
        "requested_limit": int(args.limit or 0),
        "requests_per_minute": int(args.requests_per_minute or 120),
        "min_interval_seconds": round(min_interval, 3),
        "candidate_count": len(rows),
        "updated": 0,
        "skipped": 0,
        "rate_limited": 0,
        "errors": [],
        "examples": [],
    }
    for row in rows:
        started_at = time.monotonic()
        try:
            metadata = spotify.normalize_playlist_metadata(row["url"])
            if args.dry_run:
                result = {
                    "updated": bool((metadata.get("curator_name") or "").strip()),
                    "curator_name": metadata.get("curator_name") or "",
                }
            else:
                result = apply_spotify_metadata(row, metadata, DB_PATH)
            if result.get("updated"):
                report["updated"] += 1
                if not args.dry_run:
                    save_repair_run(row, "completed", result.get("curator_name") or "", "", DB_PATH)
            else:
                report["skipped"] += 1
                if not args.dry_run:
                    save_repair_run(row, "no_owner", "", result.get("reason") or "", DB_PATH)
            if len(report["examples"]) < 12:
                report["examples"].append(
                    {
                        "playlist": row["name"],
                        "url": row["url"],
                        "spotify_curator": result.get("curator_name") or "",
                        "updated": bool(result.get("updated")),
                    }
                )
        except requests.RequestException as exc:
            status_code = getattr(getattr(exc, "response", None), "status_code", 0)
            if status_code == 429:
                wait_seconds = retry_after_seconds(exc, args.rate_limit_sleep_seconds)
                report["rate_limited"] += 1
                report["errors"].append(
                    {
                        "playlist": row["name"],
                        "url": row["url"],
                        "error": str(exc)[:500],
                        "retry_after_seconds": wait_seconds,
                    }
                )
                if not args.dry_run:
                    save_repair_run(row, "retry", "", str(exc), DB_PATH)
                report["retry_after_seconds"] = wait_seconds
                backoff_until = time.time() + wait_seconds
                write_state(
                    {
                        "status": "rate_limited",
                        "backoff_until_epoch": backoff_until,
                        "backoff_until": datetime.fromtimestamp(backoff_until, timezone.utc).isoformat(timespec="seconds"),
                        "retry_after_seconds": wait_seconds,
                        "playlist_url": row.get("url") or "",
                        "playlist_name": row.get("name") or "",
                        "updated_at": iso_now(),
                    }
                )
                break
            report["errors"].append({"playlist": row["name"], "url": row["url"], "error": str(exc)[:500]})
            if not args.dry_run:
                save_repair_run(row, "failed", "", str(exc), DB_PATH)
        except Exception as exc:
            report["errors"].append({"playlist": row["name"], "url": row["url"], "error": str(exc)[:500]})
            if not args.dry_run:
                save_repair_run(row, "failed", "", str(exc), DB_PATH)
        elapsed = time.monotonic() - started_at
        if min_interval > elapsed:
            time.sleep(min_interval - elapsed)

    if not report.get("rate_limited"):
        state = read_state()
        if state.get("status") == "rate_limited":
            state["status"] = "active"
            state["updated_at"] = iso_now()
            write_state(state)

    local_data_path("spotify_curator_repair_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
