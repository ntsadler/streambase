#!/usr/bin/env python3
"""Run Spotify curator repair batches until no untried unknown Viberate playlists remain."""
import argparse
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-limit", type=int, default=30)
    parser.add_argument("--requests-per-minute", type=int, default=3)
    parser.add_argument("--retry-sleep-seconds", type=int, default=300)
    args = parser.parse_args()

    python = ROOT / ".venv" / "bin" / "python"
    script = ROOT / "work" / "repair_unknown_viberate_curators_from_spotify.py"
    totals = {"updated": 0, "skipped": 0, "errors": 0, "candidates": 0}
    batch = 0
    print(
        json.dumps(
            {
                "event": "started",
                "started": datetime.now().isoformat(timespec="seconds"),
                "batch_limit": int(args.batch_limit),
                "requests_per_minute": int(args.requests_per_minute),
            }
        ),
        flush=True,
    )
    while True:
        batch += 1
        started = datetime.now().isoformat(timespec="seconds")
        proc = subprocess.run(
            [
                str(python),
                str(script),
                "--limit",
                str(int(args.batch_limit)),
                "--requests-per-minute",
                str(int(args.requests_per_minute)),
            ],
            cwd=str(ROOT),
            text=True,
            capture_output=True,
        )
        if proc.returncode != 0:
            print(
                json.dumps(
                    {
                        "event": "batch_error",
                        "batch": batch,
                        "started": started,
                        "returncode": proc.returncode,
                        "stderr": proc.stderr[-2000:],
                    }
                ),
                flush=True,
            )
            time.sleep(int(args.retry_sleep_seconds))
            continue
        try:
            result = json.loads(proc.stdout)
        except json.JSONDecodeError:
            print(
                json.dumps(
                    {
                        "event": "parse_error",
                        "batch": batch,
                        "started": started,
                        "stdout_tail": proc.stdout[-2000:],
                    }
                ),
                flush=True,
            )
            time.sleep(int(args.retry_sleep_seconds))
            continue

        candidates = int(result.get("candidate_count") or 0)
        updated = int(result.get("updated") or 0)
        skipped = int(result.get("skipped") or 0)
        errors = len(result.get("errors") or [])
        rate_limited = int(result.get("rate_limited") or 0)
        retry_after = int(result.get("retry_after_seconds") or 0)
        totals["updated"] += updated
        totals["skipped"] += skipped
        totals["errors"] += errors
        totals["candidates"] += candidates
        print(
            json.dumps(
                {
                    "event": "batch_finished",
                    "batch": batch,
                    "started": started,
                    "candidate_count": candidates,
                    "updated": updated,
                    "skipped": skipped,
                    "errors": errors,
                    "rate_limited": rate_limited,
                    "retry_after_seconds": retry_after,
                    "totals": totals,
                }
            ),
            flush=True,
        )
        if rate_limited:
            print(
                json.dumps(
                    {
                        "event": "paused_for_rate_limit",
                        "paused": datetime.now().isoformat(timespec="seconds"),
                        "retry_after_seconds": retry_after,
                        "totals": totals,
                    }
                ),
                flush=True,
            )
            break
        if candidates == 0:
            print(
                json.dumps(
                    {
                        "event": "completed",
                        "completed": datetime.now().isoformat(timespec="seconds"),
                        "totals": totals,
                    }
                ),
                flush=True,
            )
            break


if __name__ == "__main__":
    sys.exit(main())
