#!/usr/bin/env python3
"""Mine Viberate playlists from Cyanite reference tracks and attach to root songs."""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.database import (  # noqa: E402
    connect,
    create_mining_job,
    get_mining_query_runs,
    init_db,
    log_api_usage_event,
    now,
    plan_mining_query_runs,
    save_mined_playlist,
    save_song_playlist_target,
    update_mining_job,
    update_mining_query_run,
    upsert_playlist,
)
from src.settings import DB_PATH, local_data_path  # noqa: E402
from src.viberate import ViberateAPI, extract_playlist_items, normalize_viberate_playlist  # noqa: E402

SOURCE = "viberate_reference_track"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def split_root_ids(value: str) -> list[int]:
    ids = []
    for part in str(value or "").split(","):
        try:
            song_id = int(part.strip())
        except (TypeError, ValueError):
            continue
        if song_id and song_id not in ids:
            ids.append(song_id)
    return ids


def compact_query(track_name: str, artist_names: str) -> str:
    artist = re.split(r";|,| feat\\.| ft\\.", artist_names or "", maxsplit=1, flags=re.I)[0].strip()
    title = re.sub(r"\\s*\\([^)]*\\)", "", track_name or "").strip()
    title = re.sub(r"\\s*-\\s*(remix|edit|radio edit|remaster).*", "", title, flags=re.I).strip()
    return " ".join(part for part in [artist, title, "playlist"] if part)


def load_references(song_id: int, limit: int, min_weight: float = 0) -> list[dict]:
    limit_clause = "LIMIT ?" if int(limit or 0) > 0 else ""
    params = [f"%,{int(song_id)},%", float(min_weight or 0)]
    if int(limit or 0) > 0:
        params.append(int(limit))
    with connect(DB_PATH) as conn:
        rows = conn.execute(
            f"""
            SELECT *
            FROM cyanite_track_mining_references
            WHERE (',' || root_song_ids || ',') LIKE ?
              AND COALESCE(mining_weight, 0) >= ?
              AND COALESCE(track_name, '') != ''
              AND COALESCE(artist_names, '') != ''
            ORDER BY mining_weight DESC, playlist_count DESC, root_song_count DESC, track_name
            {limit_clause}
            """,
            params,
        ).fetchall()
    return [dict(row) for row in rows]


def ensure_run_table() -> None:
    with connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS viberate_reference_track_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                song_id INTEGER,
                reference_key TEXT,
                query TEXT,
                status TEXT DEFAULT 'planned',
                request_count INTEGER DEFAULT 0,
                result_count INTEGER DEFAULT 0,
                saved_count INTEGER DEFAULT 0,
                filtered_count INTEGER DEFAULT 0,
                error TEXT,
                started_at TEXT,
                completed_at TEXT,
                updated_at TEXT,
                UNIQUE(song_id, reference_key, query)
            )
            """
        )
        conn.commit()


def save_reference_run(song_id: int, ref: dict, query: str, **fields) -> None:
    with connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO viberate_reference_track_runs (
                song_id, reference_key, query, status, request_count, result_count,
                saved_count, filtered_count, error, started_at, completed_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(song_id, reference_key, query) DO UPDATE SET
                status=excluded.status,
                request_count=excluded.request_count,
                result_count=excluded.result_count,
                saved_count=excluded.saved_count,
                filtered_count=excluded.filtered_count,
                error=excluded.error,
                started_at=COALESCE(viberate_reference_track_runs.started_at, excluded.started_at),
                completed_at=excluded.completed_at,
                updated_at=excluded.updated_at
            """,
            (
                int(song_id),
                ref.get("reference_key") or "",
                query,
                fields.get("status") or "planned",
                int(fields.get("request_count") or 0),
                int(fields.get("result_count") or 0),
                int(fields.get("saved_count") or 0),
                int(fields.get("filtered_count") or 0),
                str(fields.get("error") or "")[:1000],
                fields.get("started_at") or utc_now(),
                fields.get("completed_at") or "",
                utc_now(),
            ),
        )
        conn.commit()


def already_completed(song_id: int, ref: dict, query: str) -> bool:
    with connect(DB_PATH) as conn:
        row = conn.execute(
            """
            SELECT status
            FROM viberate_reference_track_runs
            WHERE song_id=? AND reference_key=? AND query=?
            """,
            (int(song_id), ref.get("reference_key") or "", query),
        ).fetchone()
    return bool(row and row["status"] == "completed")


def save_playlist_for_reference(job_id: int, song_id: int, playlist: dict, ref: dict, query: str) -> bool:
    playlist_url = playlist.get("playlist_url") or ""
    if not playlist_url:
        return False
    playlist["source"] = SOURCE
    playlist["search_query"] = query
    playlist["best_song_titles"] = ref.get("root_song_titles") or ""
    playlist["matched_terms"] = f"{ref.get('track_name')} - {ref.get('artist_names')}"
    playlist["fit_reason"] = (
        f"Reference track for root song {song_id}: "
        f"{ref.get('track_name')} by {ref.get('artist_names')}; "
        f"weight {float(ref.get('mining_weight') or 0):.1f}"
    )
    playlist["fit_score"] = min(100, max(55, float(ref.get("mining_weight") or 0) / 2))
    playlist["raw"] = {
        "reference_key": ref.get("reference_key"),
        "reference_track": ref.get("track_name"),
        "reference_artist": ref.get("artist_names"),
        "root_song_ids": ref.get("root_song_ids"),
        "root_song_titles": ref.get("root_song_titles"),
        "raw": playlist.get("raw") or {},
    }
    mined_id = save_mined_playlist(job_id, playlist, DB_PATH)
    upsert_playlist(
        {
            "playlist_name": playlist.get("playlist_name"),
            "playlist_url": playlist_url,
            "curator_name": playlist.get("curator_name") or "Unknown Curator",
            "follower_count": playlist.get("follower_count") or 0,
            "spotify_description": playlist.get("spotify_description") or "",
            "related_artists": f"{ref.get('track_name')} - {ref.get('artist_names')}",
            "final_score": playlist.get("fit_score") or 0,
            "similarity_score": playlist.get("fit_score") or 0,
            "priority": "reference_track",
            "scoring_notes": json.dumps(
                {
                    "source": SOURCE,
                    "reference_key": ref.get("reference_key"),
                    "query": query,
                    "mined_playlist_id": mined_id,
                },
                ensure_ascii=True,
            ),
        },
        DB_PATH,
    )
    target_id = save_song_playlist_target(
        song_id,
        {
            "playlist_name": playlist.get("playlist_name"),
            "playlist_url": playlist_url,
            "fit_score": playlist.get("fit_score") or 0,
            "related_artists": f"{ref.get('track_name')} - {ref.get('artist_names')}",
            "raw": {
                "source": SOURCE,
                "reference_key": ref.get("reference_key"),
                "query": query,
                "mined_playlist_id": mined_id,
            },
        },
        source=SOURCE,
        fit_score=playlist.get("fit_score") or 0,
        status="target",
        notes=playlist.get("fit_reason") or "",
        db_path=DB_PATH,
    )
    return bool(target_id)


def in_follower_range(playlist: dict, follower_min: int, follower_max: int) -> bool:
    try:
        followers = int(playlist.get("follower_count") or 0)
    except (TypeError, ValueError):
        followers = 0
    return int(follower_min) <= followers <= int(follower_max)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--song-id", type=int, required=True)
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--limit-per-query", type=int, default=20)
    parser.add_argument("--requests-per-minute", type=float, default=3)
    parser.add_argument("--min-weight", type=float, default=0)
    parser.add_argument("--follower-min", type=int, default=50)
    parser.add_argument("--follower-max", type=int, default=999)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    init_db(DB_PATH)
    ensure_run_table()
    client = ViberateAPI()
    if not client.configured and not args.dry_run:
        raise SystemExit("Viberate API key is not configured.")

    refs = load_references(args.song_id, args.limit, args.min_weight)
    queries = [
        {
            "type": "reference_track",
            "query": compact_query(ref.get("track_name") or "", ref.get("artist_names") or ""),
            "reference_key": ref.get("reference_key"),
        }
        for ref in refs
    ]
    profile = {
        "profile_name": f"Reference track mining for song {args.song_id}",
        "song_id": int(args.song_id),
        "chartmetric_mining_targets": {
            "queries": queries,
            "playlist_follower_range": {"min": int(args.follower_min), "max": int(args.follower_max)},
        },
    }
    job_id = create_mining_job(profile, profile["chartmetric_mining_targets"], source=SOURCE, status="planned" if args.dry_run else "running", db_path=DB_PATH)
    plan_mining_query_runs(job_id, queries, source=SOURCE, db_path=DB_PATH)
    query_run_ids = {
        row["query"]: int(row["id"])
        for row in get_mining_query_runs(job_id, db_path=DB_PATH)
    }

    log_path = local_data_path("viberate_reference_track_mining.jsonl")
    summary = {
        "ok": True,
        "event": "started",
        "job_id": job_id,
        "song_id": int(args.song_id),
        "reference_count": len(refs),
        "requests_per_minute": float(args.requests_per_minute),
        "started_at": utc_now(),
    }
    log_path.open("a", encoding="utf-8").write(json.dumps(summary, sort_keys=True) + "\n")
    print(json.dumps(summary), flush=True)
    if args.dry_run:
        print(json.dumps({"ok": True, "job_id": job_id, "queries": queries[:20]}, indent=2))
        return 0

    interval = 60.0 / max(float(args.requests_per_minute or 3), 0.01)
    totals = {"requests": 0, "results": 0, "saved": 0, "filtered": 0, "errors": 0}
    last_request_at = 0.0
    for index, ref in enumerate(refs, start=1):
        query = compact_query(ref.get("track_name") or "", ref.get("artist_names") or "")
        if not query or already_completed(args.song_id, ref, query):
            continue
        query_run_id = query_run_ids.get(query)
        if query_run_id:
            update_mining_query_run(query_run_id, status="running", started=True, db_path=DB_PATH)
        save_reference_run(args.song_id, ref, query, status="running", started_at=utc_now())
        wait = interval - (time.monotonic() - last_request_at)
        if last_request_at and wait > 0:
            time.sleep(wait)
        try:
            response = client.search_playlists(query, limit=args.limit_per_query)
            last_request_at = time.monotonic()
            totals["requests"] += 1
            items = extract_playlist_items(response)
            result_count = 0
            saved_count = 0
            filtered_count = 0
            for raw in items:
                result_count += 1
                playlist = normalize_viberate_playlist(raw, query)
                if playlist.get("playlist_url") and in_follower_range(playlist, args.follower_min, args.follower_max):
                    if save_playlist_for_reference(job_id, args.song_id, playlist, ref, query):
                        saved_count += 1
                    else:
                        filtered_count += 1
                else:
                    filtered_count += 1
            totals["results"] += result_count
            totals["saved"] += saved_count
            totals["filtered"] += filtered_count
            save_reference_run(
                args.song_id,
                ref,
                query,
                status="completed",
                request_count=1,
                result_count=result_count,
                saved_count=saved_count,
                filtered_count=filtered_count,
                completed_at=utc_now(),
            )
            if query_run_id:
                update_mining_query_run(
                    query_run_id,
                    status="completed",
                    request_count=1,
                    result_count=result_count,
                    saved_count=saved_count,
                    filtered_count=filtered_count,
                    raw_response=response,
                    completed=True,
                    db_path=DB_PATH,
                )
            log_api_usage_event(SOURCE, "playlist_search:reference_track", query, status_code=client.last_status_code, request_count=1, credits_used=1, rate_limited=client.last_status_code == 429, db_path=DB_PATH)
            event = {
                "event": "reference_completed",
                "job_id": job_id,
                "index": index,
                "reference_count": len(refs),
                "query": query,
                "track_name": ref.get("track_name"),
                "artist_names": ref.get("artist_names"),
                "result_count": result_count,
                "saved_count": saved_count,
                "totals": totals,
                "timestamp": utc_now(),
            }
            log_path.open("a", encoding="utf-8").write(json.dumps(event, sort_keys=True) + "\n")
            print(json.dumps(event), flush=True)
        except Exception as exc:
            totals["errors"] += 1
            status_code = int(getattr(client, "last_status_code", 0) or 0)
            save_reference_run(args.song_id, ref, query, status="failed", error=str(exc), completed_at=utc_now())
            if query_run_id:
                update_mining_query_run(
                    query_run_id,
                    status="paused_rate_limit" if status_code == 429 else "failed",
                    request_count=1,
                    error=str(exc),
                    completed=status_code != 429,
                    db_path=DB_PATH,
                )
            log_api_usage_event(SOURCE, "playlist_search:reference_track", query, status_code=status_code, request_count=1, credits_used=0, rate_limited=status_code == 429, error=str(exc), db_path=DB_PATH)
            event = {
                "event": "reference_error",
                "job_id": job_id,
                "index": index,
                "query": query,
                "error": str(exc),
                "status_code": status_code,
                "totals": totals,
                "timestamp": utc_now(),
            }
            log_path.open("a", encoding="utf-8").write(json.dumps(event, sort_keys=True) + "\n")
            print(json.dumps(event), flush=True)
            if status_code == 429:
                break

    status = "completed_with_errors" if totals["errors"] else "completed"
    update_mining_job(job_id, status=status, query_count=len(refs), result_count=totals["saved"], error="", db_path=DB_PATH)
    stopped = {"ok": True, "event": "stopped", "job_id": job_id, "status": status, "totals": totals, "timestamp": utc_now()}
    log_path.open("a", encoding="utf-8").write(json.dumps(stopped, sort_keys=True) + "\n")
    print(json.dumps(stopped, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
