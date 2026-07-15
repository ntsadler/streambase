#!/usr/bin/env python3
"""Fetch deeper Viberate playlist pages for completed Cyanite seed artists."""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.database import create_mining_job, init_db, log_api_usage_event, save_mined_playlist, update_mining_job  # noqa: E402
from src.settings import DB_PATH, local_data_path  # noqa: E402
from src.viberate import ViberateAPI, extract_playlist_items, normalize_viberate_playlist  # noqa: E402
from work.run_viberate_cyanite_seed_mining import (  # noqa: E402
    SOURCE,
    connect,
    curator_allowed,
    env_float,
    env_int,
    follower_ok,
    init_seed_tables,
    save_seed_match,
)


PAGE_SOURCE = "viberate_cyanite_seed_page"


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def log_event(path, payload):
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"timestamp": utc_now(), **payload}, sort_keys=True) + "\n")


def parse_offsets(raw: str) -> list[int]:
    offsets = []
    for value in str(raw or "20").split(","):
        try:
            offset = int(value.strip())
        except ValueError:
            continue
        if offset > 0 and offset not in offsets:
            offsets.append(offset)
    return offsets or [20]


def init_page_tables(db_path):
    with connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS viberate_cyanite_seed_page_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                mining_job_id INTEGER,
                catalog_song_id INTEGER NOT NULL,
                catalog_title TEXT,
                cyanite_source_id TEXT,
                seed_rank INTEGER,
                seed_artist TEXT,
                seed_title TEXT,
                seed_spotify_track_id TEXT,
                query TEXT NOT NULL,
                page_offset INTEGER DEFAULT 20,
                status TEXT DEFAULT 'planned',
                request_count INTEGER DEFAULT 0,
                result_count INTEGER DEFAULT 0,
                saved_count INTEGER DEFAULT 0,
                filtered_count INTEGER DEFAULT 0,
                error TEXT,
                raw_response_json TEXT,
                created_at TEXT,
                started_at TEXT,
                completed_at TEXT,
                updated_at TEXT,
                UNIQUE(catalog_song_id, seed_artist, page_offset)
            )
            """
        )
        conn.commit()


def seed_rows(db_path):
    with connect(db_path) as conn:
        return [
            dict(row)
            for row in conn.execute(
                """
                SELECT catalog_song_id, catalog_title, cyanite_source_id, seed_rank,
                       seed_artist, seed_title, seed_spotify_track_id, query
                FROM viberate_cyanite_seed_runs
                WHERE status='completed'
                GROUP BY catalog_song_id, lower(seed_artist)
                ORDER BY seed_rank ASC, catalog_song_id ASC, seed_artist ASC
                """
            ).fetchall()
        ]


def create_or_resume_job(db_path, offsets, limit_per_seed, runtime_seconds):
    resume_job_id = env_int("VIBERATE_CYANITE_PAGE_RESUME_JOB_ID", 0)
    if resume_job_id:
        return resume_job_id
    profile = {
        "profile_name": "Strange Hotels Cyanite seed Viberate pagination",
        "strategy": "completed Cyanite seed artist -> Viberate artist Spotify playlists deeper pages",
        "source": PAGE_SOURCE,
        "offsets": offsets,
    }
    return create_mining_job(
        profile,
        {"offsets": offsets, "limit_per_seed": limit_per_seed, "runtime_seconds": runtime_seconds},
        source=PAGE_SOURCE,
        status="running",
        db_path=db_path,
    )


def plan_page_runs(db_path, mining_job_id, seeds, offsets):
    now = utc_now()
    planned = 0
    with connect(db_path) as conn:
        for seed in seeds:
            for offset in offsets:
                cur = conn.execute(
                    """
                    INSERT OR IGNORE INTO viberate_cyanite_seed_page_runs (
                        mining_job_id, catalog_song_id, catalog_title, cyanite_source_id,
                        seed_rank, seed_artist, seed_title, seed_spotify_track_id,
                        query, page_offset, status, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'planned', ?, ?)
                    """,
                    (
                        mining_job_id,
                        int(seed["catalog_song_id"]),
                        seed["catalog_title"],
                        seed["cyanite_source_id"],
                        int(seed["seed_rank"] or 0),
                        seed["seed_artist"],
                        seed["seed_title"] or "",
                        seed["seed_spotify_track_id"] or "",
                        seed["query"] or seed["seed_artist"],
                        int(offset),
                        now,
                        now,
                    ),
                )
                planned += cur.rowcount
        conn.commit()
    return planned


def pending_page_runs(db_path, mining_job_id):
    with connect(db_path) as conn:
        return [
            dict(row)
            for row in conn.execute(
                """
                SELECT *
                FROM viberate_cyanite_seed_page_runs
                WHERE mining_job_id = ?
                  AND status IN ('planned', 'failed', 'paused_rate_limit')
                ORDER BY page_offset ASC, seed_rank ASC, catalog_song_id ASC, id ASC
                """,
                (int(mining_job_id),),
            ).fetchall()
        ]


def update_page_run(db_path, run_id, **fields):
    allowed = {
        "status",
        "request_count",
        "result_count",
        "saved_count",
        "filtered_count",
        "error",
        "raw_response_json",
        "started_at",
        "completed_at",
        "updated_at",
    }
    payload = {key: value for key, value in fields.items() if key in allowed}
    payload.setdefault("updated_at", utc_now())
    names = ", ".join(f"{key}=?" for key in payload)
    values = list(payload.values()) + [int(run_id)]
    with connect(db_path) as conn:
        conn.execute(f"UPDATE viberate_cyanite_seed_page_runs SET {names} WHERE id=?", values)
        conn.commit()


def page_stats(db_path, mining_job_id):
    with connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS query_count,
                   SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) AS completed_count,
                   SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) AS failed_count,
                   SUM(CASE WHEN status='paused_rate_limit' THEN 1 ELSE 0 END) AS rate_limited_count,
                   COALESCE(SUM(request_count), 0) AS request_count,
                   COALESCE(SUM(saved_count), 0) AS saved_count,
                   COALESCE(SUM(filtered_count), 0) AS filtered_count
            FROM viberate_cyanite_seed_page_runs
            WHERE mining_job_id=?
            """,
            (int(mining_job_id),),
        ).fetchone()
        unique_playlists = conn.execute(
            "SELECT COUNT(DISTINCT playlist_url) FROM viberate_cyanite_playlist_matches"
        ).fetchone()[0]
    return {**dict(row), "unique_playlists_overall": unique_playlists}


def main():
    init_db(DB_PATH)
    init_seed_tables(DB_PATH)
    init_page_tables(DB_PATH)
    runtime_seconds = env_int("VIBERATE_CYANITE_PAGE_RUNTIME_SECONDS", 3600)
    limit_per_seed = env_int("VIBERATE_CYANITE_PAGE_LIMIT_PER_SEED", 20)
    offsets = parse_offsets(os.getenv("VIBERATE_CYANITE_PAGE_OFFSETS", "20"))
    follower_min = env_int("VIBERATE_CYANITE_FOLLOWER_MIN", 50)
    follower_max = env_int("VIBERATE_CYANITE_FOLLOWER_MAX", 999)
    inner_sleep = env_float("VIBERATE_CYANITE_INNER_SLEEP_SECONDS", 22.0)
    after_seed_sleep = env_float("VIBERATE_CYANITE_AFTER_SEED_SLEEP_SECONDS", 22.0)
    max_errors = env_int("VIBERATE_CYANITE_PAGE_MAX_ERRORS", 20)
    max_playlists_per_curator = env_int("VIBERATE_MAX_PLAYLISTS_PER_CURATOR", 5)

    seeds = seed_rows(DB_PATH)
    mining_job_id = create_or_resume_job(DB_PATH, offsets, limit_per_seed, runtime_seconds)
    planned = plan_page_runs(DB_PATH, mining_job_id, seeds, offsets)
    log_path = local_data_path("viberate_cyanite_seed_pagination.jsonl")
    log_event(log_path, {"event": "started", "job_id": mining_job_id, "planned": planned, "offsets": offsets, "seed_count": len(seeds)})

    client = ViberateAPI()
    stop_at = time.monotonic() + runtime_seconds
    errors = []
    processed = 0
    total_saved = 0
    paused_reason = ""

    while time.monotonic() < stop_at:
        pending = pending_page_runs(DB_PATH, mining_job_id)
        if not pending:
            break
        run = pending[0]
        update_page_run(DB_PATH, run["id"], status="running", started_at=run["started_at"] or utc_now())
        try:
            response = client.search_artist_playlist_page(
                run["seed_artist"],
                limit=limit_per_seed,
                offset=int(run["page_offset"] or 0),
                sleep_seconds=inner_sleep,
            )
            request_count = 2
            log_api_usage_event(
                PAGE_SOURCE,
                "artist_playlist_search_page",
                f"{run['seed_artist']} offset {run['page_offset']}",
                status_code=int(client.last_status_code or 200),
                request_count=request_count,
                credits_used=request_count,
                db_path=DB_PATH,
            )
            result_count = 0
            saved_count = 0
            filtered_count = 0
            for raw in extract_playlist_items(response):
                result_count += 1
                playlist = normalize_viberate_playlist(raw, run["seed_artist"])
                playlist["source"] = SOURCE
                playlist["best_song_titles"] = run["catalog_title"]
                playlist["fit_reason"] = f"Cyanite similar seed artist page {run['page_offset']}: {run['seed_artist']}"
                if follower_ok(playlist, follower_min, follower_max):
                    if curator_allowed(DB_PATH, playlist, max_playlists_per_curator):
                        save_mined_playlist(mining_job_id, playlist, db_path=DB_PATH)
                        saved_count += save_seed_match(DB_PATH, mining_job_id, run, playlist)
                    else:
                        filtered_count += 1
                else:
                    filtered_count += 1
            update_page_run(
                DB_PATH,
                run["id"],
                status="completed",
                request_count=request_count,
                result_count=result_count,
                saved_count=saved_count,
                filtered_count=filtered_count,
                raw_response_json=json.dumps(response, ensure_ascii=True),
                completed_at=utc_now(),
            )
            processed += 1
            total_saved += saved_count
            stats = page_stats(DB_PATH, mining_job_id)
            update_mining_job(
                mining_job_id,
                status="running",
                query_count=stats["query_count"],
                result_count=stats["saved_count"],
                error="; ".join(errors[:5]),
                db_path=DB_PATH,
            )
            log_event(
                log_path,
                {
                    "event": "page_completed",
                    "job_id": mining_job_id,
                    "song_id": run["catalog_song_id"],
                    "song": run["catalog_title"],
                    "seed_artist": run["seed_artist"],
                    "offset": run["page_offset"],
                    "result_count": result_count,
                    "saved_count": saved_count,
                    "filtered_count": filtered_count,
                    "stats": stats,
                },
            )
        except Exception as exc:
            message = str(exc)
            errors.append(f"{run['seed_artist']} offset {run['page_offset']}: {message}")
            status_code = int(getattr(client, "last_status_code", 0) or 0)
            rate_limited = status_code == 429 or "429" in message
            log_api_usage_event(
                PAGE_SOURCE,
                "artist_playlist_search_page",
                f"{run['seed_artist']} offset {run['page_offset']}",
                status_code=status_code,
                request_count=1,
                credits_used=0,
                rate_limited=rate_limited,
                error=message,
                db_path=DB_PATH,
            )
            update_page_run(
                DB_PATH,
                run["id"],
                status="paused_rate_limit" if rate_limited else "failed",
                request_count=1,
                error=message,
                completed_at=None if rate_limited else utc_now(),
            )
            log_event(log_path, {"event": "page_error", "job_id": mining_job_id, "seed_artist": run["seed_artist"], "offset": run["page_offset"], "error": message})
            if rate_limited:
                paused_reason = f"Rate limited while searching {run['seed_artist']} offset {run['page_offset']}."
                break
            if len(errors) >= max_errors:
                paused_reason = f"Error budget reached ({max_errors})."
                break
        if time.monotonic() + after_seed_sleep >= stop_at:
            break
        time.sleep(after_seed_sleep)

    stats = page_stats(DB_PATH, mining_job_id)
    pending_count = len(pending_page_runs(DB_PATH, mining_job_id))
    if paused_reason:
        status = "paused"
    elif pending_count:
        status = "paused"
        paused_reason = f"Runtime budget reached ({runtime_seconds} seconds)."
    else:
        status = "completed_with_errors" if errors else "completed"
    update_mining_job(
        mining_job_id,
        status=status,
        query_count=stats["query_count"],
        result_count=stats["saved_count"],
        error=paused_reason or "; ".join(errors[:5]),
        db_path=DB_PATH,
    )
    summary = {
        "ok": True,
        "job_id": mining_job_id,
        "status": status,
        "processed_page_queries": processed,
        "saved_relationships_this_run": total_saved,
        "pending_page_queries": pending_count,
        "stats": stats,
        "paused_reason": paused_reason,
        "errors": errors[:10],
    }
    log_event(log_path, {"event": "stopped", **summary})
    print(json.dumps(summary, indent=2))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
