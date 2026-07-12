#!/usr/bin/env python3
import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.database import (
    connect,
    create_mining_job,
    init_db,
    log_api_usage_event,
    save_mined_playlist,
    save_song_playlist_target,
    update_mining_job,
)
from src.settings import DB_PATH, local_data_path
from src.viberate import ViberateAPI, extract_playlist_items, normalize_viberate_playlist


SOURCE = "viberate_cyanite_seed"


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def env_int(name, default):
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def env_float(name, default):
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def init_seed_tables(db_path):
    with connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS viberate_cyanite_seed_runs (
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
                UNIQUE(catalog_song_id, seed_artist)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS viberate_cyanite_playlist_matches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                mining_job_id INTEGER,
                catalog_song_id INTEGER NOT NULL,
                catalog_title TEXT,
                playlist_url TEXT NOT NULL,
                playlist_name TEXT,
                curator_name TEXT,
                follower_count INTEGER DEFAULT 0,
                seed_artist TEXT,
                seed_title TEXT,
                seed_rank INTEGER,
                seed_spotify_track_id TEXT,
                source_playlist_id TEXT,
                fit_score REAL DEFAULT 0,
                raw_json TEXT,
                created_at TEXT,
                updated_at TEXT,
                UNIQUE(catalog_song_id, playlist_url, seed_artist)
            )
            """
        )
        conn.commit()


def normalize_seed_artist(value):
    text = " ".join(str(value or "").split())
    if not text:
        return ""
    # Cyanite occasionally renders collabs as one artist string; Viberate artist
    # search usually works better on the leading artist. Keep "&" and commas
    # because they are part of real names like "Earth, Wind & Fire".
    lowered = text.lower()
    for separator in [" feat. ", " ft. ", " featuring ", " x "]:
        if separator in lowered:
            idx = lowered.index(separator)
            text = text[:idx].strip()
            lowered = text.lower()
            break
    # Our Cyanite row parser can mistake title subtitles for artist text when the
    # rendered display is "Artist - Song - Version". For Viberate, the leading
    # artist is the useful search term.
    if " - " in text:
        text = text.split(" - ", 1)[0].strip()
    return text


def seed_queue(db_path, max_seed_artists_per_song):
    with connect(db_path) as conn:
        rows = [
            dict(row)
            for row in conn.execute(
                """
                SELECT catalog_song_id, catalog_title, cyanite_source_id, rank,
                       result_artist, result_title, spotify_track_id
                FROM cyanite_similarity_seed_songs
                WHERE coalesce(result_artist, '') != ''
                ORDER BY rank ASC, catalog_song_id ASC
                """
            ).fetchall()
        ]
    per_song = {}
    queue = []
    seen = set()
    for row in rows:
        song_id = int(row["catalog_song_id"])
        if per_song.get(song_id, 0) >= max_seed_artists_per_song:
            continue
        artist = normalize_seed_artist(row["result_artist"])
        if not artist:
            continue
        key = (song_id, artist.lower())
        if key in seen:
            continue
        seen.add(key)
        per_song[song_id] = per_song.get(song_id, 0) + 1
        queue.append(
            {
                "catalog_song_id": song_id,
                "catalog_title": row["catalog_title"],
                "cyanite_source_id": row["cyanite_source_id"],
                "seed_rank": int(row["rank"] or 0),
                "seed_artist": artist,
                "seed_title": row["result_title"] or "",
                "seed_spotify_track_id": row["spotify_track_id"] or "",
                "query": artist,
            }
        )
    return queue


def plan_seed_runs(db_path, mining_job_id, queue):
    now = utc_now()
    planned = 0
    with connect(db_path) as conn:
        for item in queue:
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO viberate_cyanite_seed_runs (
                    mining_job_id, catalog_song_id, catalog_title, cyanite_source_id,
                    seed_rank, seed_artist, seed_title, seed_spotify_track_id,
                    query, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'planned', ?, ?)
                """,
                (
                    mining_job_id,
                    item["catalog_song_id"],
                    item["catalog_title"],
                    item["cyanite_source_id"],
                    item["seed_rank"],
                    item["seed_artist"],
                    item["seed_title"],
                    item["seed_spotify_track_id"],
                    item["query"],
                    now,
                    now,
                ),
            )
            planned += cur.rowcount
        conn.commit()
    return planned


def pending_seed_runs(db_path, mining_job_id):
    with connect(db_path) as conn:
        return [
            dict(row)
            for row in conn.execute(
                """
                SELECT *
                FROM viberate_cyanite_seed_runs
                WHERE mining_job_id = ?
                  AND status IN ('planned', 'failed', 'paused_rate_limit')
                ORDER BY seed_rank ASC, catalog_song_id ASC, id ASC
                """,
                (int(mining_job_id),),
            ).fetchall()
        ]


def run_stats(db_path, mining_job_id):
    with connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT
              COUNT(*) AS query_count,
              SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) AS completed_count,
              SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) AS failed_count,
              SUM(CASE WHEN status='paused_rate_limit' THEN 1 ELSE 0 END) AS rate_limited_count,
              COALESCE(SUM(request_count), 0) AS request_count,
              COALESCE(SUM(saved_count), 0) AS saved_count,
              COALESCE(SUM(filtered_count), 0) AS filtered_count
            FROM viberate_cyanite_seed_runs
            WHERE mining_job_id = ?
            """,
            (int(mining_job_id),),
        ).fetchone()
        unique_playlists = conn.execute(
            """
            SELECT COUNT(DISTINCT playlist_url)
            FROM viberate_cyanite_playlist_matches
            WHERE mining_job_id = ?
            """,
            (int(mining_job_id),),
        ).fetchone()[0]
        song_targets = conn.execute(
            """
            SELECT COUNT(*)
            FROM song_playlist_targets
            WHERE source = ?
            """,
            (SOURCE,),
        ).fetchone()[0]
    return {**dict(row), "unique_playlists": unique_playlists, "song_targets": song_targets}


def follower_ok(playlist, follower_min, follower_max):
    try:
        followers = int(playlist.get("follower_count") or 0)
    except (TypeError, ValueError):
        followers = 0
    return follower_min <= followers <= follower_max


def score_song_playlist(db_path, catalog_song_id, playlist, run):
    playlist_url = playlist.get("playlist_url") or ""
    followers = int(playlist.get("follower_count") or 0)
    with connect(db_path) as conn:
        overlap_count = conn.execute(
            """
            SELECT COUNT(DISTINCT seed_artist)
            FROM viberate_cyanite_playlist_matches
            WHERE catalog_song_id = ? AND playlist_url = ?
            """,
            (int(catalog_song_id), playlist_url),
        ).fetchone()[0]
    rank = int(run.get("seed_rank") or 99)
    rank_bonus = max(0, 16 - rank * 2)
    overlap_bonus = min(45, max(0, int(overlap_count) - 1) * 15)
    follower_bonus = 20 if 50 <= followers <= 999 else 12 if followers < 50 else 4
    return min(100, 42 + rank_bonus + follower_bonus + overlap_bonus)


def save_seed_match(db_path, mining_job_id, run, playlist):
    now = utc_now()
    raw = playlist.get("raw_json") or playlist.get("raw") or {}
    raw_text = raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=True)
    playlist_url = playlist.get("playlist_url") or ""
    if not playlist_url:
        return 0
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO viberate_cyanite_playlist_matches (
                mining_job_id, catalog_song_id, catalog_title, playlist_url,
                playlist_name, curator_name, follower_count, seed_artist, seed_title,
                seed_rank, seed_spotify_track_id, source_playlist_id, fit_score,
                raw_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(catalog_song_id, playlist_url, seed_artist) DO UPDATE SET
                playlist_name=excluded.playlist_name,
                curator_name=excluded.curator_name,
                follower_count=excluded.follower_count,
                fit_score=max(viberate_cyanite_playlist_matches.fit_score, excluded.fit_score),
                raw_json=excluded.raw_json,
                updated_at=excluded.updated_at
            """,
            (
                mining_job_id,
                int(run["catalog_song_id"]),
                run["catalog_title"],
                playlist_url,
                playlist.get("playlist_name") or "",
                playlist.get("curator_name") or "",
                int(playlist.get("follower_count") or 0),
                run["seed_artist"],
                run["seed_title"] or "",
                int(run["seed_rank"] or 0),
                run["seed_spotify_track_id"] or "",
                playlist.get("source_playlist_id") or "",
                float(playlist.get("fit_score") or 0),
                raw_text,
                now,
                now,
            ),
        )
        conn.commit()
    fit_score = score_song_playlist(db_path, run["catalog_song_id"], playlist, run)
    playlist["fit_score"] = fit_score
    playlist["related_artists"] = run["seed_artist"]
    playlist["notes"] = (
        f"Viberate playlist hit from Cyanite similar seed "
        f"{run['seed_artist']} - {run['seed_title']}"
    )
    playlist["raw"] = {
        "seed_run": {
            "catalog_song_id": run["catalog_song_id"],
            "catalog_title": run["catalog_title"],
            "seed_rank": run["seed_rank"],
            "seed_artist": run["seed_artist"],
            "seed_title": run["seed_title"],
            "seed_spotify_track_id": run["seed_spotify_track_id"],
        },
        "playlist": raw,
    }
    save_song_playlist_target(
        run["catalog_song_id"],
        playlist,
        source=SOURCE,
        fit_score=fit_score,
        status="target",
        notes=playlist["notes"],
        db_path=db_path,
    )
    with connect(db_path) as conn:
        conn.execute(
            """
            UPDATE viberate_cyanite_playlist_matches
            SET fit_score = ?, updated_at = ?
            WHERE catalog_song_id = ? AND playlist_url = ?
            """,
            (fit_score, now, int(run["catalog_song_id"]), playlist_url),
        )
        conn.commit()
    return 1


def update_seed_run(db_path, run_id, **fields):
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
        conn.execute(f"UPDATE viberate_cyanite_seed_runs SET {names} WHERE id=?", values)
        conn.commit()


def log_event(path, payload):
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"timestamp": utc_now(), **payload}, sort_keys=True) + "\n")


def main():
    init_db(DB_PATH)
    init_seed_tables(DB_PATH)
    runtime_seconds = env_int("VIBERATE_CYANITE_RUNTIME_SECONDS", 3600)
    max_seed_artists_per_song = env_int("VIBERATE_CYANITE_MAX_SEED_ARTISTS_PER_SONG", 3)
    limit_per_seed = env_int("VIBERATE_CYANITE_LIMIT_PER_SEED", 20)
    follower_min = env_int("VIBERATE_CYANITE_FOLLOWER_MIN", 50)
    follower_max = env_int("VIBERATE_CYANITE_FOLLOWER_MAX", 999)
    inner_sleep = env_float("VIBERATE_CYANITE_INNER_SLEEP_SECONDS", 22.0)
    after_seed_sleep = env_float("VIBERATE_CYANITE_AFTER_SEED_SLEEP_SECONDS", 22.0)
    max_errors = env_int("VIBERATE_CYANITE_MAX_ERRORS", 20)
    resume_job_id = env_int("VIBERATE_CYANITE_RESUME_JOB_ID", 0)

    profile = {
        "profile_name": "Strange Hotels Cyanite seed Viberate mining",
        "strategy": "catalog_song -> Cyanite similar artist -> Viberate artist Spotify playlists",
        "source": SOURCE,
        "max_seed_artists_per_song": max_seed_artists_per_song,
        "follower_range": {"min": follower_min, "max": follower_max},
    }
    queue = seed_queue(DB_PATH, max_seed_artists_per_song)
    if resume_job_id:
        mining_job_id = resume_job_id
    else:
        mining_job_id = create_mining_job(
            profile,
            {
                "seed_query_count": len(queue),
                "limit_per_seed": limit_per_seed,
                "runtime_seconds": runtime_seconds,
                "rate_limit": {
                    "artist_search_to_playlist_sleep_seconds": inner_sleep,
                    "after_seed_sleep_seconds": after_seed_sleep,
                },
            },
            source=SOURCE,
            status="running",
            db_path=DB_PATH,
        )
    planned = plan_seed_runs(DB_PATH, mining_job_id, queue)
    log_path = local_data_path("viberate_cyanite_seed_mining.jsonl")
    log_event(log_path, {"event": "started", "job_id": mining_job_id, "planned": planned, "queue_count": len(queue)})

    client = ViberateAPI()
    stop_at = time.monotonic() + runtime_seconds
    errors = []
    processed = 0
    total_saved = 0
    paused_reason = ""

    while time.monotonic() < stop_at:
        pending = pending_seed_runs(DB_PATH, mining_job_id)
        if not pending:
            break
        run = pending[0]
        update_seed_run(DB_PATH, run["id"], status="running", started_at=run["started_at"] or utc_now())
        try:
            response = client.search_artist_playlist_page(
                run["seed_artist"],
                limit=limit_per_seed,
                offset=0,
                sleep_seconds=inner_sleep,
            )
            request_count = 2
            log_api_usage_event(
                SOURCE,
                "artist_playlist_search",
                run["seed_artist"],
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
                playlist["fit_reason"] = f"Cyanite similar seed artist: {run['seed_artist']}"
                if follower_ok(playlist, follower_min, follower_max):
                    save_mined_playlist(mining_job_id, playlist, db_path=DB_PATH)
                    saved_count += save_seed_match(DB_PATH, mining_job_id, run, playlist)
                else:
                    filtered_count += 1
            update_seed_run(
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
            stats = run_stats(DB_PATH, mining_job_id)
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
                    "event": "seed_completed",
                    "job_id": mining_job_id,
                    "song_id": run["catalog_song_id"],
                    "song": run["catalog_title"],
                    "seed_artist": run["seed_artist"],
                    "result_count": result_count,
                    "saved_count": saved_count,
                    "filtered_count": filtered_count,
                    "stats": stats,
                },
            )
        except Exception as exc:
            message = str(exc)
            errors.append(f"{run['seed_artist']}: {message}")
            status_code = int(getattr(client, "last_status_code", 0) or 0)
            rate_limited = status_code == 429 or "429" in message
            log_api_usage_event(
                SOURCE,
                "artist_playlist_search",
                run["seed_artist"],
                status_code=status_code,
                request_count=1,
                credits_used=0,
                rate_limited=rate_limited,
                error=message,
                db_path=DB_PATH,
            )
            update_seed_run(
                DB_PATH,
                run["id"],
                status="paused_rate_limit" if rate_limited else "failed",
                request_count=1,
                error=message,
                completed_at=None if rate_limited else utc_now(),
            )
            log_event(log_path, {"event": "seed_error", "job_id": mining_job_id, "seed_artist": run["seed_artist"], "error": message})
            if rate_limited:
                paused_reason = f"Rate limited while searching {run['seed_artist']}."
                break
            if len(errors) >= max_errors:
                paused_reason = f"Error budget reached ({max_errors})."
                break
        if time.monotonic() + after_seed_sleep >= stop_at:
            break
        time.sleep(after_seed_sleep)

    stats = run_stats(DB_PATH, mining_job_id)
    pending_count = len(pending_seed_runs(DB_PATH, mining_job_id))
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
        "processed_seed_queries": processed,
        "saved_relationships_this_run": total_saved,
        "pending_seed_queries": pending_count,
        "stats": stats,
        "paused_reason": paused_reason,
        "errors": errors[:10],
    }
    log_event(log_path, {"event": "stopped", **summary})
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
