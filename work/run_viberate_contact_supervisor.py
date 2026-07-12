#!/usr/bin/env python3
"""Run ranked Viberate/Cyanite contact enrichment batches until a stop time."""
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.settings import local_data_path  # noqa: E402


def env_int(name, default):
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def seconds_until_local_time(value):
    value = str(value or "").strip()
    if not value:
        value = "10:00"
    try:
        hour_text, minute_text = value.split(":", 1)
        hour = int(hour_text)
        minute = int(minute_text)
    except ValueError:
        hour, minute = 10, 0
    now = datetime.now().astimezone()
    stop_at = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if stop_at <= now:
        stop_at = stop_at + timedelta(days=1)
    return max(60, int((stop_at - now).total_seconds()))


def log_event(path, payload):
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"timestamp": datetime.now(timezone.utc).isoformat(), **payload}, sort_keys=True) + "\n")


def main():
    batch_limit = env_int("VIBERATE_CONTACT_BATCH_LIMIT", 50)
    sleep_seconds = env_int("VIBERATE_CONTACT_BATCH_SLEEP_SECONDS", 60)
    all_saved = str(os.getenv("VIBERATE_CONTACT_ALL_SAVED", "")).strip().lower() in {"1", "true", "yes"}
    runtime_seconds = seconds_until_local_time(os.getenv("VIBERATE_CONTACT_STOP_TIME", "10:00"))
    stop_at = time.monotonic() + runtime_seconds
    log_path = local_data_path("viberate_contact_supervisor.jsonl")
    log_event(log_path, {"event": "started", "runtime_seconds": runtime_seconds, "batch_limit": batch_limit})
    batch_index = 0
    totals = {
        "promoted_playlists": 0,
        "contact_searches": 0,
        "contact_methods_saved": 0,
        "contactable_playlists": 0,
    }
    while time.monotonic() < stop_at:
        batch_index += 1
        cmd = [
            sys.executable,
            str(ROOT / "work" / "enrich_top_viberate_song_targets.py"),
            "--limit",
            str(batch_limit),
        ]
        if all_saved:
            cmd.append("--all-saved")
        started = time.monotonic()
        proc = subprocess.run(cmd, cwd=str(ROOT), text=True, capture_output=True)
        duration = round(time.monotonic() - started, 2)
        payload = {
            "event": "batch_finished",
            "batch_index": batch_index,
            "returncode": proc.returncode,
            "duration_seconds": duration,
        }
        if proc.stdout.strip():
            try:
                result = json.loads(proc.stdout)
            except json.JSONDecodeError:
                result = {"raw_stdout": proc.stdout[-2000:]}
            payload["result"] = result
            if isinstance(result, dict):
                for key in totals:
                    totals[key] += int(result.get(key) or 0)
                if int(result.get("candidate_count") or 0) == 0:
                    log_event(log_path, {**payload, "event": "no_candidates_remaining", "totals": totals})
                    break
        if proc.stderr.strip():
            payload["stderr"] = proc.stderr[-2000:]
        log_event(log_path, payload)
        if proc.returncode != 0:
            time.sleep(min(300, sleep_seconds * 2))
        elif time.monotonic() + sleep_seconds < stop_at:
            time.sleep(sleep_seconds)
    log_event(log_path, {"event": "stopped", "batch_count": batch_index, "totals": totals})
    print(json.dumps({"ok": True, "batch_count": batch_index, "totals": totals}, indent=2))


if __name__ == "__main__":
    main()
