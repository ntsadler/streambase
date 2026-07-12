#!/usr/bin/env python3
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.database import get_release_songs, init_db
from src.mining_targets import build_catalog_mining_profile
from src.settings import DB_PATH, local_data_path
from src.viberate_mining import run_viberate_mining


KEYWORD_BATCHES = [
    [
        "under 1000 followers indie curator",
        "under 1000 followers alternative curator",
        "under 1000 followers shoegaze curator",
        "under 1000 followers psych curator",
        "under 1000 followers garage curator",
        "micro curator indie submissions",
        "micro curator alternative submissions",
        "micro curator shoegaze submissions",
        "micro curator psych submissions",
        "micro curator garage submissions",
        "small curator indie submissions",
        "small curator alternative submissions",
        "small curator shoegaze submissions",
        "small curator psych submissions",
        "small curator garage submissions",
        "emerging curator indie submissions",
        "emerging curator alternative submissions",
        "emerging curator shoegaze submissions",
        "emerging curator psych submissions",
        "new curator indie submissions",
        "new curator alternative submissions",
        "new curator shoegaze submissions",
        "new curator psych submissions",
        "low follower indie playlist",
        "low follower alternative playlist",
        "low follower shoegaze playlist",
        "low follower psych playlist",
        "low follower garage rock playlist",
        "tiny indie playlist",
        "tiny alternative playlist",
        "tiny shoegaze playlist",
        "tiny psych playlist",
        "tiny garage rock playlist",
        "niche indie curator",
        "niche alternative curator",
        "niche shoegaze curator",
        "niche psych curator",
        "niche garage rock curator",
        "boutique indie playlist",
        "boutique alternative playlist",
        "boutique shoegaze playlist",
        "boutique psych playlist",
        "boutique garage rock playlist",
        "under 500 followers indie playlist",
        "under 500 followers alternative playlist",
        "under 500 followers shoegaze playlist",
        "under 500 followers psych playlist",
        "under 500 followers garage rock playlist",
        "under 100 followers indie playlist",
        "under 100 followers shoegaze playlist",
    ],
    [
        "accepting submissions indie playlist",
        "accepting submissions alternative playlist",
        "accepting submissions shoegaze playlist",
        "accepting submissions psych playlist",
        "accepting submissions garage rock playlist",
        "playlist submissions indie",
        "playlist submissions alternative",
        "playlist submissions shoegaze",
        "playlist submissions psych rock",
        "submit music indie",
        "submit music alternative",
        "submit music shoegaze",
        "submit music psych rock",
        "curator submission playlist",
        "indie curator submissions",
        "alternative curator submissions",
        "shoegaze curator submissions",
        "garage rock curator submissions",
        "psych rock curator submissions",
        "new release indie playlist",
        "new release alternative playlist",
        "new release shoegaze playlist",
        "new release psych playlist",
        "new indie releases playlist",
        "new alternative releases playlist",
        "new shoegaze releases playlist",
        "new psych releases playlist",
        "hidden gems indie playlist",
        "hidden gems alternative playlist",
        "hidden gems shoegaze playlist",
        "hidden gems psych playlist",
        "hidden gems garage rock playlist",
        "underground indie playlist",
        "underground alternative playlist",
        "underground shoegaze playlist",
        "underground psych playlist",
        "underground garage rock playlist",
        "fresh tracks indie playlist",
        "fresh tracks alternative playlist",
        "fresh tracks shoegaze playlist",
        "fresh tracks psych playlist",
        "college radio indie playlist",
        "college radio alternative playlist",
        "college radio shoegaze playlist",
        "local bands indie playlist",
        "local bands alternative playlist",
        "DIY indie bands playlist",
        "DIY alternative playlist",
        "small curator indie playlist",
        "small curator alternative playlist",
    ],
    [
        "dream pop submissions",
        "bedroom pop submissions",
        "lo fi submissions",
        "indie pop submissions",
        "alt pop submissions",
        "alt rnb submissions",
        "electro indie submissions",
        "indie dance submissions",
        "indie disco submissions",
        "micro curator dream pop",
        "micro curator bedroom pop",
        "micro curator lo fi",
        "micro curator indie pop",
        "micro curator alt pop",
        "micro curator alt rnb",
        "small curator dream pop",
        "small curator bedroom pop",
        "small curator lo fi",
        "small curator indie pop",
        "small curator alt pop",
        "small curator alt rnb",
        "new release dream pop",
        "new release bedroom pop",
        "new release lo fi",
        "new release indie pop",
        "new release alt pop",
        "new release alt rnb",
        "new release electro indie",
        "new release indie dance",
        "hidden gems dream pop",
        "hidden gems bedroom pop",
        "hidden gems lo fi",
        "hidden gems indie pop",
        "hidden gems alt pop",
        "hidden gems alt rnb",
        "underground dream pop",
        "underground bedroom pop",
        "underground lo fi",
        "underground indie pop",
        "underground alt pop",
        "local dream pop",
        "local bedroom pop",
        "local lo fi",
        "DIY dream pop",
        "DIY bedroom pop",
        "DIY lo fi",
        "college radio dream pop",
        "college radio lo fi",
        "fresh tracks dream pop",
        "fresh tracks lo fi",
    ],
]


def build_profile(keywords):
    profile = build_catalog_mining_profile(get_release_songs(), follower_min=50, follower_max=999)
    profile["cyanite_seed_artists"] = []
    profile["core_genre_tags"] = []
    profile["chartmetric_mining_targets"] = {
        "playlist_follower_range": {"min": 50, "max": 999},
        "chartmetric_queries": [],
        "playlist_keyword_searches": keywords,
        "reference_artists_to_search": [],
        "track_examples_to_search": [],
        "playlist_lanes": [],
        "genre_mood_terms": [
            "indie",
            "alternative",
            "shoegaze",
            "dream pop",
            "psych",
            "garage",
            "curator",
            "submissions",
            "new release",
            "hidden gems",
            "underground",
            "micro",
            "small",
            "low follower",
        ],
    }
    return profile


def log_event(path, payload):
    payload = {"timestamp": datetime.now(timezone.utc).isoformat(), **payload}
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


def seconds_until_local_time(value):
    value = str(value or "").strip()
    if not value:
        return 8 * 60 * 60
    try:
        hour_text, minute_text = value.split(":", 1)
        hour = int(hour_text)
        minute = int(minute_text)
    except ValueError:
        return 8 * 60 * 60
    now = datetime.now().astimezone()
    stop_at = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if stop_at <= now:
        stop_at = stop_at + timedelta(days=1)
    return max(60, int((stop_at - now).total_seconds()))


def main():
    init_db(DB_PATH)
    log_path = local_data_path("viberate_keyword_supervisor.jsonl")
    runtime_seconds = seconds_until_local_time(os.getenv("VIBERATE_SUPERVISOR_STOP_TIME", ""))
    stop_at = time.monotonic() + runtime_seconds
    log_event(log_path, {"ok": True, "event": "supervisor_started", "runtime_seconds": runtime_seconds})
    batch_index = 0
    while time.monotonic() < stop_at:
        keywords = KEYWORD_BATCHES[batch_index % len(KEYWORD_BATCHES)]
        batch_index += 1
        try:
            result = run_viberate_mining(
                build_profile(keywords),
                limit_per_query=20,
                max_queries=50,
                dry_run=False,
                resume_job_id=None,
                max_requests_per_run=1000,
                max_runtime_seconds=max(60, int(stop_at - time.monotonic())),
                max_errors_per_run=80,
                db_path=DB_PATH,
            )
            log_event(log_path, {"ok": True, "batch_index": batch_index, "result": result})
        except Exception as exc:
            log_event(log_path, {"ok": False, "batch_index": batch_index, "error": str(exc)})
            time.sleep(60)
    log_event(log_path, {"ok": True, "event": "supervisor_stopped"})


if __name__ == "__main__":
    main()
