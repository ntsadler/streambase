from typing import Dict, List


DEFAULT_FOLLOWER_RANGE = {"min": 1000, "max": 75000}
DEFAULT_EXCLUSION_RULES = [
    "exclude Spotify editorial playlists",
    "exclude major-label branded playlists",
    "exclude inactive playlists",
    "exclude mega playlists above 75,000 followers unless contactability is strong",
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
