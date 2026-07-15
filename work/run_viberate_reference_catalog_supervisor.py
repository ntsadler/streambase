#!/usr/bin/env python3
"""Run reference-track Viberate mining across the Strange Hotels catalog."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.database import connect, init_db  # noqa: E402
from src.settings import DB_PATH, local_data_path  # noqa: E402
from work.run_viberate_reference_track_mining import (  # noqa: E402
    compact_query,
    ensure_run_table,
    load_references,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def log_event(path: Path, payload: dict) -> None:
    event = {"timestamp": utc_now(), **payload}
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, sort_keys=True) + "\n")
    print(json.dumps(event), flush=True)


def catalog_songs(limit: int = 0) -> list[dict]:
    sql = """
        SELECT s.id AS song_id, s.title AS song_title, COUNT(r.id) AS reference_count,
               MAX(r.mining_weight) AS max_weight
        FROM songs s
        JOIN cyanite_track_mining_references r
          ON (',' || r.root_song_ids || ',') LIKE '%,' || s.id || ',%'
        GROUP BY s.id, s.title
        ORDER BY s.id
    """
    if limit:
        sql += f" LIMIT {int(limit)}"
    with connect(DB_PATH) as conn:
        return [dict(row) for row in conn.execute(sql).fetchall()]


def completed_top_reference_count(song_id: int, reference_limit: int, min_weight: float) -> tuple[int, int]:
    refs = load_references(song_id, reference_limit, min_weight)
    if not refs:
        return (0, 0)
    keys = [(ref.get("reference_key") or "", compact_query(ref.get("track_name") or "", ref.get("artist_names") or "")) for ref in refs]
    with connect(DB_PATH) as conn:
        completed = 0
        for reference_key, query in keys:
            row = conn.execute(
                """
                SELECT 1
                FROM viberate_reference_track_runs
                WHERE song_id=? AND reference_key=? AND query=? AND status='completed'
                """,
                (int(song_id), reference_key, query),
            ).fetchone()
            completed += 1 if row else 0
    return completed, len(refs)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference-limit", type=int, default=50)
    parser.add_argument("--limit-per-query", type=int, default=20)
    parser.add_argument("--requests-per-minute", type=float, default=3)
    parser.add_argument("--follower-min", type=int, default=50)
    parser.add_argument("--follower-max", type=int, default=999)
    parser.add_argument("--min-weight", type=float, default=0)
    parser.add_argument("--song-limit", type=int, default=0)
    parser.add_argument("--sleep-between-songs", type=int, default=30)
    args = parser.parse_args()

    init_db(DB_PATH)
    ensure_run_table()
    log_path = local_data_path("viberate_reference_catalog_supervisor.jsonl")
    songs = catalog_songs(args.song_limit)
    log_event(
        log_path,
        {
            "event": "catalog_supervisor_started",
            "song_count": len(songs),
            "reference_limit": int(args.reference_limit),
            "requests_per_minute": float(args.requests_per_minute),
            "follower_min": int(args.follower_min),
            "follower_max": int(args.follower_max),
        },
    )

    python = ROOT / ".venv" / "bin" / "python"
    child = ROOT / "work" / "run_viberate_reference_track_mining.py"
    for index, song in enumerate(songs, start=1):
        song_id = int(song["song_id"])
        completed, total = completed_top_reference_count(song_id, args.reference_limit, args.min_weight)
        if total and completed >= total:
            log_event(
                log_path,
                {
                    "event": "song_skipped_completed",
                    "index": index,
                    "song_count": len(songs),
                    "song_id": song_id,
                    "song_title": song.get("song_title"),
                    "completed_references": completed,
                    "total_references": total,
                },
            )
            continue

        log_event(
            log_path,
            {
                "event": "song_started",
                "index": index,
                "song_count": len(songs),
                "song_id": song_id,
                "song_title": song.get("song_title"),
                "completed_references": completed,
                "total_references": total,
            },
        )
        started = time.monotonic()
        proc = subprocess.run(
            [
                str(python),
                str(child),
                "--song-id",
                str(song_id),
                "--limit",
                str(int(args.reference_limit)),
                "--limit-per-query",
                str(int(args.limit_per_query)),
                "--requests-per-minute",
                str(float(args.requests_per_minute)),
                "--follower-min",
                str(int(args.follower_min)),
                "--follower-max",
                str(int(args.follower_max)),
                "--min-weight",
                str(float(args.min_weight)),
            ],
            cwd=str(ROOT),
            text=True,
            capture_output=True,
        )
        log_event(
            log_path,
            {
                "event": "song_finished",
                "index": index,
                "song_count": len(songs),
                "song_id": song_id,
                "song_title": song.get("song_title"),
                "returncode": proc.returncode,
                "elapsed_seconds": round(time.monotonic() - started, 1),
                "stdout_tail": proc.stdout[-2000:],
                "stderr_tail": proc.stderr[-2000:],
            },
        )
        if proc.returncode != 0:
            time.sleep(60)
        else:
            time.sleep(max(0, int(args.sleep_between_songs)))

    log_event(log_path, {"event": "catalog_supervisor_finished", "song_count": len(songs)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
