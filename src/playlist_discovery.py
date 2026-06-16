from typing import Callable, Dict, List, Optional

from src.similarity_engine import split_terms
from src.song_analyzer import (
    analyze_song_fit,
    is_new_release_context,
    score_spotify_playlist_candidates,
)
from src.spotify_api import ENGLISH_SPOTIFY_MARKETS, search_spotify_playlists_multi_market


def artist_playlist_searches(song_fit: Dict, max_artists: int = 3) -> List[Dict]:
    song = song_fit.get("song") or {}
    release = song_fit.get("release_guidance") or {}
    artists = song.get("reference_artists") or []
    if isinstance(artists, str):
        artists = split_terms(artists)
    descriptors = [term for term in split_terms(song.get("descriptors", "")) if len(term) > 2]
    lane_terms = [
        (lane.get("lane") or "").split(" / ")[0]
        for lane in song_fit.get("recommended_playlist_lanes", [])
        if lane.get("lane")
    ]
    searches = []
    for artist in artists[:max_artists]:
        seeds = [
            f"{artist} emerging artists playlist",
            f"{artist} independent artists playlist",
            " ".join([artist] + descriptors[:2] + ["artist discovery", "playlist"]).strip(),
        ]
        if lane_terms:
            seeds.append(" ".join([artist, lane_terms[0], "emerging artists", "playlist"]).strip())
        if release.get("exclude_new_release_playlists"):
            seeds = [f"{seed} evergreen" for seed in seeds if not is_new_release_context(seed)]
        for seed in seeds:
            query = " ".join(seed.split())
            if query:
                searches.append({"source": "track_artist", "search_query": query})

    seen = set()
    out = []
    for item in searches:
        key = item["search_query"].lower()
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out[:8]


def released_track_playlist_plan(
    spotify_track: Dict,
    saved_playlists: Optional[List[Dict]] = None,
    cyanite_profile: Optional[Dict] = None,
) -> Dict:
    track = {**(spotify_track or {}), "release_context": "already_released"}
    song_fit = analyze_song_fit(
        None,
        title=track.get("title", ""),
        artist=track.get("artist", ""),
        reference_artists=track.get("reference_artists", ""),
        descriptors=track.get("descriptors", ""),
        saved_playlists=saved_playlists or [],
        spotify_track=track,
        reference_tracks=[],
        cyanite_profile=cyanite_profile or {},
    )
    artist_searches = artist_playlist_searches(song_fit)
    discovery = song_fit.get("discovery_searches") or []
    seen = set()
    searches = []
    for item in artist_searches + discovery:
        query = " ".join((item.get("search_query") or "").split())
        if query and query.lower() not in seen:
            seen.add(query.lower())
            searches.append({**item, "search_query": query})
    return {"song_fit": song_fit, "searches": searches}


def discover_released_track_playlists(
    spotify_track: Dict,
    saved_playlists: Optional[List[Dict]] = None,
    query_limit: int = 4,
    limit_per_query: int = 5,
    markets: Optional[List[str]] = None,
    search_fn: Optional[Callable[[List[str], int, List[str]], Dict]] = None,
    cyanite_profile: Optional[Dict] = None,
) -> Dict:
    plan = released_track_playlist_plan(spotify_track, saved_playlists, cyanite_profile)
    queries = [item["search_query"] for item in plan["searches"][: max(1, int(query_limit or 1))]]
    if not queries:
        return {**plan, "ok": False, "error": "No playlist search queries could be generated.", "candidates": []}

    runner = search_fn or search_spotify_playlists_multi_market
    result = runner(queries, int(limit_per_query or 5), markets or ENGLISH_SPOTIFY_MARKETS)
    candidates = score_spotify_playlist_candidates(plan["song_fit"], result.get("playlists", []), saved_playlists or [])
    return {
        **plan,
        "ok": result.get("ok", False),
        "error": result.get("error", ""),
        "queries_run": queries,
        "markets": result.get("markets", markets or ENGLISH_SPOTIFY_MARKETS),
        "candidates": candidates,
    }


def _catalog_cyanite_profile(song: Dict) -> Dict:
    def split(value):
        return [item.strip() for item in str(value or "").split(";") if item.strip()]

    return {
        "source": song.get("analysis_source") or song.get("source") or "catalog",
        "genres": split(song.get("genre_tags")),
        "moods": split(song.get("mood_tags")),
        "instruments": split(song.get("instrumentation")),
        "energy": song.get("energy", ""),
        "voice": song.get("vocal_style", ""),
        "descriptors": "; ".join(
            item
            for item in [
                song.get("genre_tags", ""),
                song.get("mood_tags", ""),
                song.get("instrumentation", ""),
                song.get("vocal_style", ""),
                song.get("energy", ""),
            ]
            if item
        ),
    }


def catalog_song_playlist_plan(
    song: Dict,
    saved_playlists: Optional[List[Dict]] = None,
    spotify_track: Optional[Dict] = None,
) -> Dict:
    cyanite_profile = _catalog_cyanite_profile(song)
    release_status = (song.get("release_status") or "").lower()
    track = {
        "title": song.get("title", ""),
        "artist": song.get("artist_name", ""),
        "reference_artists": song.get("reference_artists", ""),
        "descriptors": cyanite_profile.get("descriptors", ""),
        "spotify_url": song.get("spotify_url", ""),
        "release_context": "already_released" if release_status == "released" else "new_release",
    }
    if spotify_track:
        track.update({k: v for k, v in spotify_track.items() if v not in {"", None}})
        track["release_context"] = "already_released" if release_status == "released" or track.get("spotify_url") else track.get("release_context", "new_release")

    song_fit = analyze_song_fit(
        None,
        title=track.get("title", ""),
        artist=track.get("artist", ""),
        reference_artists=track.get("reference_artists", ""),
        descriptors=track.get("descriptors", ""),
        saved_playlists=saved_playlists or [],
        spotify_track=track,
        reference_tracks=[],
        cyanite_profile=cyanite_profile,
    )
    artist_searches = artist_playlist_searches(song_fit)
    discovery = song_fit.get("discovery_searches") or []
    seen = set()
    searches = []
    for item in artist_searches + discovery:
        query = " ".join((item.get("search_query") or "").split())
        if query and query.lower() not in seen:
            seen.add(query.lower())
            searches.append({**item, "search_query": query})
    return {"song_fit": song_fit, "searches": searches, "cyanite_profile": cyanite_profile}


def discover_catalog_song_playlists(
    song: Dict,
    saved_playlists: Optional[List[Dict]] = None,
    spotify_track: Optional[Dict] = None,
    query_limit: int = 4,
    limit_per_query: int = 5,
    markets: Optional[List[str]] = None,
    search_fn: Optional[Callable[[List[str], int, List[str]], Dict]] = None,
) -> Dict:
    plan = catalog_song_playlist_plan(song, saved_playlists, spotify_track)
    queries = [item["search_query"] for item in plan["searches"][: max(1, int(query_limit or 1))]]
    if not queries:
        return {**plan, "ok": False, "error": "No playlist search queries could be generated.", "candidates": []}

    runner = search_fn or search_spotify_playlists_multi_market
    result = runner(queries, int(limit_per_query or 5), markets or ENGLISH_SPOTIFY_MARKETS)
    candidates = score_spotify_playlist_candidates(plan["song_fit"], result.get("playlists", []), saved_playlists or [])
    return {
        **plan,
        "ok": result.get("ok", False),
        "error": result.get("error", ""),
        "queries_run": queries,
        "markets": result.get("markets", markets or ENGLISH_SPOTIFY_MARKETS),
        "candidates": candidates,
    }
