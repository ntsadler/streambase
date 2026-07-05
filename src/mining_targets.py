from collections import Counter
from typing import Dict, Iterable, List


DEFAULT_FOLLOWER_RANGE = {"min": 50, "max": 999}
DEFAULT_EXCLUSION_RULES = [
    "exclude Spotify editorial playlists",
    "exclude major-label branded playlists",
    "exclude inactive playlists",
    "exclude playlists at or above 1,000 followers",
    "exclude playlists explicitly focused on new releases for older catalog tracks",
]


def _pair_terms(terms: List[str], max_pairs: int = 4) -> List[str]:
    pairs = []
    for i, first in enumerate(terms):
        for second in terms[i + 1:]:
            pairs.append(f"{first} + {second}")
            if len(pairs) >= max_pairs:
                return pairs
    return pairs


def _split_terms(value) -> List[str]:
    if isinstance(value, list):
        raw_terms = value
    else:
        raw_terms = str(value or "").replace(",", ";").split(";")
    terms = []
    seen = set()
    for raw in raw_terms:
        term = " ".join(str(raw or "").strip().split())
        key = term.lower()
        if term and key not in seen:
            seen.add(key)
            terms.append(term)
    return terms


def _top_terms(rows: Iterable[Dict], field: str, limit: int) -> List[str]:
    counts = Counter()
    original = {}
    for row in rows:
        for term in _split_terms(row.get(field)):
            key = term.lower()
            counts[key] += 1
            original.setdefault(key, term)
    return [original[key] for key, _ in counts.most_common(limit)]


def build_chartmetric_targets(profile: Dict) -> Dict:
    genres = profile.get("core_genre_tags", [])[:6]
    moods = profile.get("core_mood_tags", [])[:6]
    references = profile.get("strongest_reference_artists", [])[:8]
    tracks = profile.get("track_examples", [])[:8]

    reference_pairs = _pair_terms(references)
    playlist_keyword_terms = genres[:4] + moods[:4]
    keyword_searches = []
    for term in playlist_keyword_terms:
        keyword_searches.append(f"{term} playlist")
    for pair in reference_pairs:
        keyword_searches.append(f"playlists containing {pair}")

    return {
        "reference_artists_to_search": references,
        "track_examples_to_search": tracks,
        "playlist_keyword_searches": keyword_searches[:12],
        "genre_mood_terms": playlist_keyword_terms,
        "playlist_follower_range": DEFAULT_FOLLOWER_RANGE,
        "playlist_activity_rule": "prefer playlists updated in the last 60 days",
        "playlist_exclusion_rules": DEFAULT_EXCLUSION_RULES,
        "chartmetric_queries": [
            f"playlists containing {pair}" for pair in reference_pairs
        ] + [
            f"playlists tagged {term}" for term in playlist_keyword_terms[:6]
        ],
    }


def build_catalog_mining_profile(
    catalog_rows: List[Dict],
    follower_min: int = 50,
    follower_max: int = 999,
    max_genres: int = 8,
    max_moods: int = 8,
    max_references: int = 10,
    max_tracks: int = 12,
) -> Dict:
    released_rows = [
        row for row in catalog_rows
        if str(row.get("release_status") or "").strip().lower() in {"released", "already released"}
    ] or list(catalog_rows)
    genres = _top_terms(released_rows, "genre_tags", max_genres)
    moods = _top_terms(released_rows, "mood_tags", max_moods)
    references = _top_terms(released_rows, "reference_artists", max_references)
    categories = _top_terms(released_rows, "recommended_playlist_categories", max_genres)
    tracks = []
    seen_tracks = set()
    for row in released_rows:
        title = " ".join(str(row.get("title") or row.get("file_name") or "").strip().split())
        key = title.lower()
        if title and key not in seen_tracks:
            seen_tracks.add(key)
            tracks.append(title)
        if len(tracks) >= max_tracks:
            break

    profile = {
        "profile_name": "Strange Hotels Catalog Playlist Miner",
        "song_count": len(released_rows),
        "core_genre_tags": genres,
        "core_mood_tags": moods,
        "strongest_reference_artists": references,
        "track_examples": tracks,
        "playlist_keyword_terms": categories,
    }
    targets = build_chartmetric_targets(profile)
    targets["playlist_follower_range"] = {"min": int(follower_min or 50), "max": int(follower_max or 999)}
    targets["playlist_keyword_searches"] = (categories + targets.get("playlist_keyword_searches", []))[:16]
    targets["playlist_exclusion_rules"] = DEFAULT_EXCLUSION_RULES
    targets["playlist_lanes"] = [
        {"name": "Sound-alike curators", "terms": references[:6]},
        {"name": "Genre pockets", "terms": genres[:6]},
        {"name": "Mood pockets", "terms": moods[:6]},
        {"name": "Catalog track trails", "terms": tracks[:6]},
    ]
    profile["chartmetric_mining_targets"] = targets
    return profile
