from typing import Dict, List, Optional

from src.chartmetric import ChartmetricAPI, extract_playlist_items, normalize_chartmetric_playlist
from src.database import bulk_save_mined_playlists, create_mining_job, update_mining_job
from src.mining_targets import build_chartmetric_targets


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


def run_chartmetric_mining(
    profile: Dict,
    client: Optional[ChartmetricAPI] = None,
    limit_per_query: int = 25,
    max_queries: int = 12,
    dry_run: Optional[bool] = None,
    db_path=None,
) -> Dict:
    client = client or ChartmetricAPI()
    targets = profile.get("chartmetric_mining_targets") or build_chartmetric_targets(profile)
    queries = chartmetric_queries_from_profile({**profile, "chartmetric_mining_targets": targets}, max_queries)
    should_dry_run = (not client.configured) if dry_run is None else dry_run
    job_id = create_mining_job(profile, {"queries": queries, **targets}, status="planned" if should_dry_run else "running", db_path=db_path) if db_path else create_mining_job(profile, {"queries": queries, **targets}, status="planned" if should_dry_run else "running")

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

    playlists = []
    errors = []
    for item in queries:
        query = item["query"]
        try:
            if item["type"] == "artist":
                response = client.search_playlists_by_artist(query, limit_per_query)
            else:
                response = client.search_playlists(query, limit_per_query)
            for raw in extract_playlist_items(response):
                playlists.append(normalize_chartmetric_playlist(raw, query))
        except Exception as exc:
            errors.append(f"{query}: {exc}")

    saved = bulk_save_mined_playlists(job_id, playlists, db_path=db_path) if db_path else bulk_save_mined_playlists(job_id, playlists)
    status = "completed_with_errors" if errors else "completed"
    if db_path:
        update_mining_job(job_id, status=status, query_count=len(queries), result_count=saved, error="; ".join(errors[:5]), db_path=db_path)
    else:
        update_mining_job(job_id, status=status, query_count=len(queries), result_count=saved, error="; ".join(errors[:5]))
    return {
        "ok": not errors or bool(playlists),
        "dry_run": False,
        "job_id": job_id,
        "queries": queries,
        "playlists": playlists,
        "saved_count": saved,
        "errors": errors,
        "message": f"Chartmetric mining {status}. Saved {saved} playlist(s).",
    }
