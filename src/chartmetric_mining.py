import os
import time
from typing import Dict, List, Optional

from src.chartmetric import ChartmetricAPI, extract_playlist_items, normalize_chartmetric_playlist
from src.database import (
    create_mining_job,
    get_mining_job,
    get_mining_query_runs,
    log_api_usage_event,
    plan_mining_query_runs,
    save_mined_playlist,
    update_mining_job,
    update_mining_query_run,
)
from src.mining_targets import build_chartmetric_targets


def _safe_int(value, default=0):
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return default


def chartmetric_queries_from_profile(profile: Dict, limit: int = 20) -> List[Dict]:
    targets = profile.get("chartmetric_mining_targets") or build_chartmetric_targets(profile)
    queries = []
    for query in targets.get("chartmetric_queries", []):
        queries.append({"type": "query", "query": query})
    for query in targets.get("playlist_keyword_searches", []):
        queries.append({"type": "keyword", "query": query})
    for artist in targets.get("reference_artists_to_search", []):
        queries.append({"type": "artist", "query": artist})
    for track in targets.get("track_examples_to_search", []):
        queries.append({"type": "track", "query": track})

    seen = set()
    unique = []
    for item in queries:
        q = " ".join(str(item.get("query", "")).split())
        if not q or q.lower() in seen:
            continue
        seen.add(q.lower())
        unique.append({**item, "query": q})
    return unique[:limit]


def score_mined_playlist(playlist: Dict, profile: Dict, targets: Dict) -> Dict:
    text = " ".join([
        str(playlist.get("playlist_name") or ""),
        str(playlist.get("spotify_description") or ""),
        str(playlist.get("search_query") or playlist.get("query") or ""),
    ]).lower()
    terms = []
    for field in ("core_genre_tags", "core_mood_tags", "playlist_keyword_terms"):
        terms.extend(profile.get(field, []) or [])
    terms.extend(targets.get("genre_mood_terms", []) or [])
    matched = []
    for term in terms:
        clean = " ".join(str(term or "").lower().split())
        if clean and clean in text and clean not in matched:
            matched.append(clean)

    followers = _safe_int(playlist.get("follower_count"))
    follower_max = _safe_int(targets.get("playlist_follower_range", {}).get("max"), 999)
    follower_score = 30 if 25 <= followers <= follower_max else 15 if followers <= follower_max else 0
    term_score = min(60, len(matched) * 15)
    name_bonus = 10 if any(term in str(playlist.get("playlist_name") or "").lower() for term in matched[:3]) else 0
    score = min(100, follower_score + term_score + name_bonus)
    return {
        "fit_score": score,
        "fit_reason": f"{followers:,} followers; matched {', '.join(matched[:4]) or 'the source query'}",
        "matched_terms": "; ".join(matched[:10]),
        "follower_tier": "under_1000" if followers <= follower_max else "over_limit",
    }


def playlist_within_follower_range(playlist: Dict, targets: Dict) -> bool:
    followers = _safe_int(playlist.get("follower_count"))
    follower_range = targets.get("playlist_follower_range", {})
    follower_min = _safe_int(follower_range.get("min"), 0)
    follower_max = _safe_int(follower_range.get("max"), 999)
    return follower_min <= followers <= follower_max


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _header_int(headers: Dict, names: List[str]):
    lowered = {str(k).lower(): v for k, v in (headers or {}).items()}
    for name in names:
        value = lowered.get(name.lower())
        if value in (None, ""):
            continue
        try:
            return int(float(value))
        except (TypeError, ValueError):
            continue
    return None


def _remaining_credits(headers: Dict):
    return _header_int(headers, [
        "x-ratelimit-remaining",
        "x-rate-limit-remaining",
        "x-credits-remaining",
        "x-credit-remaining",
        "credits-remaining",
    ])


def _credits_used(headers: Dict) -> int:
    return _header_int(headers, [
        "x-credits-used",
        "x-credit-cost",
        "credits-used",
    ]) or 1


def _query_totals(query_runs: List[Dict]) -> Dict:
    return {
        "request_count": sum(int(row.get("request_count") or 0) for row in query_runs),
        "saved_count": sum(int(row.get("saved_count") or 0) for row in query_runs),
        "filtered_count": sum(int(row.get("filtered_count") or 0) for row in query_runs),
        "completed_count": sum(1 for row in query_runs if row.get("status") == "completed"),
        "error_count": sum(1 for row in query_runs if row.get("status") == "failed"),
    }


def run_chartmetric_mining(
    profile: Dict,
    client: Optional[ChartmetricAPI] = None,
    limit_per_query: int = 25,
    max_queries: int = 12,
    dry_run: Optional[bool] = None,
    db_path=None,
    resume_job_id: Optional[int] = None,
    max_requests_per_run: Optional[int] = None,
    max_runtime_seconds: Optional[int] = None,
    max_errors_per_run: Optional[int] = None,
    sleep_seconds: Optional[float] = None,
    min_remaining_credits: Optional[int] = None,
) -> Dict:
    client = client or ChartmetricAPI()
    targets = profile.get("chartmetric_mining_targets") or build_chartmetric_targets(profile)
    queries = chartmetric_queries_from_profile({**profile, "chartmetric_mining_targets": targets}, max_queries)
    should_dry_run = (not client.configured) if dry_run is None else dry_run
    max_requests = max_requests_per_run if max_requests_per_run is not None else _env_int("CHARTMETRIC_MAX_REQUESTS_PER_RUN", 1000)
    max_runtime = max_runtime_seconds if max_runtime_seconds is not None else _env_int("CHARTMETRIC_MAX_RUNTIME_SECONDS", 4 * 60 * 60)
    max_errors = max_errors_per_run if max_errors_per_run is not None else _env_int("CHARTMETRIC_MAX_ERRORS_PER_RUN", 10)
    sleep_for = sleep_seconds if sleep_seconds is not None else _env_float("CHARTMETRIC_REQUEST_SLEEP_SECONDS", 0.0)
    min_credits = min_remaining_credits if min_remaining_credits is not None else _env_int("CHARTMETRIC_MIN_REMAINING_CREDITS", 0)
    job_id = int(resume_job_id or 0)
    if job_id and not get_mining_job(job_id, db_path=db_path):
        job_id = 0
    if not job_id:
        job_id = create_mining_job(profile, {"queries": queries, **targets, "budgets": {"max_requests_per_run": max_requests, "max_runtime_seconds": max_runtime, "max_errors_per_run": max_errors, "min_remaining_credits": min_credits}}, status="planned" if should_dry_run else "running", db_path=db_path) if db_path else create_mining_job(profile, {"queries": queries, **targets, "budgets": {"max_requests_per_run": max_requests, "max_runtime_seconds": max_runtime, "max_errors_per_run": max_errors, "min_remaining_credits": min_credits}}, status="planned" if should_dry_run else "running")
    plan_mining_query_runs(job_id, queries, source="chartmetric", db_path=db_path) if db_path else plan_mining_query_runs(job_id, queries, source="chartmetric")

    if should_dry_run:
        if db_path:
            update_mining_job(job_id, status="planned", query_count=len(queries), result_count=0, db_path=db_path)
        else:
            update_mining_job(job_id, status="planned", query_count=len(queries), result_count=0)
        return {
            "ok": True,
            "dry_run": True,
            "job_id": job_id,
            "queries": queries,
            "playlists": [],
            "message": "Chartmetric mining job planned. Add CHARTMETRIC_API_TOKEN to run live mining.",
        }

    update_mining_job(job_id, status="running", query_count=len(queries), db_path=db_path) if db_path else update_mining_job(job_id, status="running", query_count=len(queries))
    start_time = time.monotonic()
    request_count = 0
    saved_count = 0
    filtered_out = 0
    errors = []
    paused_reason = ""
    query_runs = get_mining_query_runs(job_id, statuses=["planned", "running", "failed", "paused_rate_limit", "paused_quota"], db_path=db_path) if db_path else get_mining_query_runs(job_id, statuses=["planned", "running", "failed", "paused_rate_limit", "paused_quota"])
    for query_run in query_runs:
        if request_count >= max_requests:
            paused_reason = f"Request budget reached ({max_requests})."
            break
        if max_runtime and time.monotonic() - start_time >= max_runtime:
            paused_reason = f"Runtime budget reached ({max_runtime} seconds)."
            break
        if len(errors) >= max_errors:
            paused_reason = f"Error budget reached ({max_errors})."
            break
        query = query_run["query"]
        query_type = query_run["query_type"]
        update_mining_query_run(query_run["id"], status="running", started=True, db_path=db_path) if db_path else update_mining_query_run(query_run["id"], status="running", started=True)
        try:
            if query_type == "artist":
                response = client.search_playlists_by_artist(query, limit_per_query)
            else:
                response = client.search_playlists(query, limit_per_query)
            request_count += 1
            headers = getattr(client, "last_response_headers", {}) or {}
            status_code = int(getattr(client, "last_status_code", 0) or 200)
            remaining = _remaining_credits(headers)
            credits = _credits_used(headers)
            log_api_usage_event("chartmetric", f"playlist_search:{query_type}", query, status_code=status_code, request_count=1, credits_used=credits, remaining_credits=remaining, rate_limited=status_code == 429, db_path=db_path) if db_path else log_api_usage_event("chartmetric", f"playlist_search:{query_type}", query, status_code=status_code, request_count=1, credits_used=credits, remaining_credits=remaining, rate_limited=status_code == 429)
            if remaining is not None and min_credits and remaining <= min_credits:
                paused_reason = f"Remaining credits reached guardrail ({remaining} <= {min_credits})."
                update_mining_query_run(query_run["id"], status="paused_quota", request_count=1, error=paused_reason, raw_response=response, db_path=db_path) if db_path else update_mining_query_run(query_run["id"], status="paused_quota", request_count=1, error=paused_reason, raw_response=response)
                break
            result_count = 0
            query_saved = 0
            query_filtered = 0
            for raw in extract_playlist_items(response):
                result_count += 1
                playlist = normalize_chartmetric_playlist(raw, query)
                playlist.update(score_mined_playlist(playlist, profile, targets))
                if playlist_within_follower_range(playlist, targets):
                    saved_id = save_mined_playlist(job_id, playlist, db_path=db_path) if db_path else save_mined_playlist(job_id, playlist)
                    if saved_id:
                        query_saved += 1
                        saved_count += 1
                else:
                    query_filtered += 1
                    filtered_out += 1
            update_mining_query_run(query_run["id"], status="completed", request_count=1, result_count=result_count, saved_count=query_saved, filtered_count=query_filtered, raw_response=response, completed=True, db_path=db_path) if db_path else update_mining_query_run(query_run["id"], status="completed", request_count=1, result_count=result_count, saved_count=query_saved, filtered_count=query_filtered, raw_response=response, completed=True)
            all_runs = get_mining_query_runs(job_id, db_path=db_path) if db_path else get_mining_query_runs(job_id)
            totals = _query_totals(all_runs)
            update_mining_job(job_id, status="running", query_count=len(all_runs), result_count=totals["saved_count"], error="; ".join(errors[:5]), db_path=db_path) if db_path else update_mining_job(job_id, status="running", query_count=len(all_runs), result_count=totals["saved_count"], error="; ".join(errors[:5]))
            if sleep_for:
                time.sleep(sleep_for)
        except Exception as exc:
            message = f"{query}: {exc}"
            errors.append(message)
            response = getattr(exc, "response", None)
            status_code = int(getattr(response, "status_code", 0) or getattr(client, "last_status_code", 0) or 0)
            rate_limited = status_code == 429 or "429" in str(exc)
            log_api_usage_event("chartmetric", f"playlist_search:{query_type}", query, status_code=status_code, request_count=1, credits_used=0, rate_limited=rate_limited, error=str(exc), db_path=db_path) if db_path else log_api_usage_event("chartmetric", f"playlist_search:{query_type}", query, status_code=status_code, request_count=1, credits_used=0, rate_limited=rate_limited, error=str(exc))
            update_mining_query_run(query_run["id"], status="paused_rate_limit" if rate_limited else "failed", request_count=1, error=str(exc), completed=not rate_limited, db_path=db_path) if db_path else update_mining_query_run(query_run["id"], status="paused_rate_limit" if rate_limited else "failed", request_count=1, error=str(exc), completed=not rate_limited)
            if rate_limited:
                paused_reason = f"Rate limited while running {query}."
                break

    all_runs = get_mining_query_runs(job_id, db_path=db_path) if db_path else get_mining_query_runs(job_id)
    totals = _query_totals(all_runs)
    unfinished = [row for row in all_runs if row.get("status") not in {"completed"}]
    if paused_reason:
        status = "paused"
    elif unfinished:
        status = "completed_with_errors" if errors else "paused"
    else:
        status = "completed_with_errors" if errors else "completed"
    update_mining_job(job_id, status=status, query_count=len(all_runs), result_count=totals["saved_count"], error=paused_reason or "; ".join(errors[:5]), db_path=db_path) if db_path else update_mining_job(job_id, status=status, query_count=len(all_runs), result_count=totals["saved_count"], error=paused_reason or "; ".join(errors[:5]))
    return {
        "ok": not errors or totals["saved_count"] > 0,
        "dry_run": False,
        "job_id": job_id,
        "queries": queries,
        "playlists": [],
        "saved_count": totals["saved_count"],
        "filtered_out_count": totals["filtered_count"],
        "request_count": request_count,
        "completed_query_count": totals["completed_count"],
        "paused": bool(paused_reason),
        "paused_reason": paused_reason,
        "errors": errors,
        "message": f"Chartmetric mining {status}. Saved {totals['saved_count']} under-1,000 playlist(s). Filtered out {totals['filtered_count']}.",
    }
