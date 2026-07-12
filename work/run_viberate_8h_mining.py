#!/usr/bin/env python3
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.database import get_mining_jobs, get_release_songs, init_db
from src.mining_targets import build_catalog_mining_profile
from src.settings import DB_PATH, local_data_path
from src.viberate_mining import run_viberate_mining


def latest_viberate_job_id():
    for job in get_mining_jobs(DB_PATH):
        if job.get("source") == "viberate" and job.get("status") in {"paused", "planned", "running"}:
            return int(job.get("id") or 0)
    return 0


def main():
    init_db(DB_PATH)
    songs = get_release_songs()
    if not songs:
        raise SystemExit("No catalog songs found. Add songs to the Catalog before mining.")

    profile = build_catalog_mining_profile(songs, follower_min=50, follower_max=999)
    job_id = latest_viberate_job_id()
    result = run_viberate_mining(
        profile,
        limit_per_query=20,
        max_queries=40,
        dry_run=False,
        resume_job_id=job_id or None,
        max_requests_per_run=1000,
        max_runtime_seconds=8 * 60 * 60,
        max_errors_per_run=50,
        db_path=DB_PATH,
    )
    out = local_data_path("viberate_8h_mining_result.json")
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
