import os
import re
from collections import Counter
from typing import Dict, List, Optional

from src.database import connect
from src.chartmetric_mining import (
    chartmetric_queries_from_profile,
    run_chartmetric_mining,
)
from src.viberate import ViberateAPI, extract_playlist_items, normalize_viberate_playlist

VIBERATE_GENRES = {
    "pop": "2",
    "r&b": "4",
    "rnb": "4",
    "electronic": "6",
    "electronic dance": "6",
    "electro": "6",
    "house": "6",
    "rock": "7",
}

VIBERATE_SUBGENRES = {
    "indie": "9",
    "indie pop": "9",
    "contemporary r&b": "14",
    "funk": "15",
    "soul": "16",
    "neo soul": "17",
    "dance": "30",
    "house": "31",
    "electro": "38",
}

INDIE_CURATOR_PLAYLIST_TYPE = "3"


def _viberate_sleep_seconds(value: Optional[float]) -> float:
    if value is not None:
        return float(value)
    configured_sleep = os.getenv("VIBERATE_REQUEST_SLEEP_SECONDS")
    if configured_sleep not in (None, ""):
        try:
            return float(configured_sleep)
        except (TypeError, ValueError):
            return 20.0
    try:
        requests_per_minute = float(os.getenv("VIBERATE_REQUESTS_PER_MINUTE", "3"))
    except (TypeError, ValueError):
        requests_per_minute = 3.0
    return 60.0 / requests_per_minute if requests_per_minute > 0 else 20.0


def cyanite_seed_artists(db_path=None, limit: int = 20) -> List[str]:
    counts = Counter()
    try:
        with connect(db_path) if db_path else connect() as conn:
            rows = conn.execute(
                "SELECT related_artists FROM song_playlist_targets "
                "WHERE source='cyanite_seed' AND coalesce(related_artists,'')!=''"
            ).fetchall()
    except Exception:
        return []
    for row in rows:
        text = row["related_artists"] if hasattr(row, "keys") else row[0]
        for raw in re.split(r"[;,]", text or ""):
            name = " ".join(str(raw or "").strip().split())
            key = name.lower()
            if not name or key == "strange hotels" or key.isdigit():
                continue
            counts[name] += 1
    return [name for name, _ in counts.most_common(limit)]


def viberate_queries_from_profile(profile: Dict, limit: int = 20) -> List[Dict]:
    queries = []
    targets = profile.get("chartmetric_mining_targets") or {}
    for artist in (profile.get("cyanite_seed_artists") or [])[:50]:
        clean = " ".join(str(artist or "").split())
        if clean:
            queries.append({"type": "artist_playlist", "query": clean})

    for term in (profile.get("core_genre_tags") or [])[:8]:
        clean = " ".join(str(term or "").split())
        key = clean.lower()
        genre_id = VIBERATE_GENRES.get(key)
        subgenre_id = VIBERATE_SUBGENRES.get(key)
        if genre_id:
            queries.append({
                "type": "chart",
                "query": f"genre={clean}; playlist_type=Indie Curator",
            })
        if subgenre_id:
            queries.append({
                "type": "chart",
                "query": f"subgenre={clean}; playlist_type=Indie Curator",
            })

    for lane in targets.get("playlist_lanes", []):
        if lane.get("name") != "Mood pockets":
            continue
        for term in (lane.get("terms") or [])[:6]:
            clean = " ".join(str(term or "").split())
            if clean and not clean.isdigit():
                queries.append({"type": "keyword", "query": f"{clean} playlist"})

    for item in chartmetric_queries_from_profile(profile, limit * 2):
        raw_query = " ".join(str(item.get("query") or "").split())
        if not raw_query:
            continue
        query = raw_query
        lowered = query.lower()
        if lowered.startswith("playlists tagged "):
            query = f"{query[len('playlists tagged '):]} playlist"
        elif lowered.startswith("playlists containing "):
            query = f"{query[len('playlists containing '):]} playlist"
        elif not lowered.endswith("playlist") and item.get("type") in {"query", "keyword"}:
            query = f"{query} playlist"
        queries.append({**item, "query": query})

    seen = set()
    unique = []
    for item in queries:
        key = item["query"].lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique[:limit]


def _parse_chart_query(query: str) -> Dict:
    params = {"playlist_types": INDIE_CURATOR_PLAYLIST_TYPE}
    for part in str(query or "").split(";"):
        if "=" not in part:
            continue
        key, value = [x.strip() for x in part.split("=", 1)]
        lookup = value.lower()
        if key == "genre":
            genre_id = VIBERATE_GENRES.get(lookup)
            if genre_id:
                params["genres"] = genre_id
        elif key == "subgenre":
            subgenre_id = VIBERATE_SUBGENRES.get(lookup)
            if subgenre_id:
                params["subgenres"] = subgenre_id
        elif key == "playlist_type":
            params["playlist_types"] = INDIE_CURATOR_PLAYLIST_TYPE
    return params


def _parse_artist_query(query: str) -> tuple[str, int]:
    artist = str(query or "")
    offset = 0
    if "|" in artist:
        artist, extra = artist.split("|", 1)
        for part in extra.split(";"):
            if "=" not in part:
                continue
            key, value = [x.strip() for x in part.split("=", 1)]
            if key == "offset":
                try:
                    offset = max(0, int(value))
                except (TypeError, ValueError):
                    offset = 0
    return " ".join(artist.split()), offset


def _search_viberate_playlists(client: ViberateAPI, query_run: Dict, limit: int, sleep_seconds: float = 0.0) -> Dict:
    query = query_run.get("query") or ""
    if query_run.get("query_type") == "chart":
        return client.chart_playlists(_parse_chart_query(query), limit=limit)
    if query_run.get("query_type") == "artist_playlist":
        artist, offset = _parse_artist_query(query)
        return client.search_artist_playlist_page(artist, limit=limit, offset=offset, sleep_seconds=sleep_seconds)
    return client.search_playlists(query, limit)


def run_viberate_mining(
    profile: Dict,
    client: Optional[ViberateAPI] = None,
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
    sleep_for = _viberate_sleep_seconds(sleep_seconds)
    profile = dict(profile or {})
    profile.setdefault("cyanite_seed_artists", cyanite_seed_artists(db_path=db_path, limit=80))
    return run_chartmetric_mining(
        profile,
        client=client or ViberateAPI(),
        limit_per_query=limit_per_query,
        max_queries=max_queries,
        dry_run=dry_run,
        db_path=db_path,
        resume_job_id=resume_job_id,
        max_requests_per_run=max_requests_per_run,
        max_runtime_seconds=max_runtime_seconds,
        max_errors_per_run=max_errors_per_run,
        sleep_seconds=sleep_for,
        min_remaining_credits=min_remaining_credits,
        provider="viberate",
        provider_label="Viberate",
        queries_from_profile=viberate_queries_from_profile,
        extract_items=extract_playlist_items,
        normalize_playlist=normalize_viberate_playlist,
        search_playlists=lambda api_client, query_run, limit: _search_viberate_playlists(
            api_client, query_run, limit, sleep_seconds=sleep_for
        ),
    )
