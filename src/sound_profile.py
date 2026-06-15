from collections import Counter
from typing import Dict, Iterable, List

from src.mining_targets import build_chartmetric_targets
from src.similarity_engine import split_terms


TAG_FIELDS = {
    "genre_tags": "core_genre_tags",
    "mood_tags": "core_mood_tags",
    "instrumentation": "recurring_instrumentation",
    "vocal_style": "recurring_vocal_styles",
}


def top_terms(rows: Iterable[Dict], field: str, limit: int = 8) -> List[str]:
    counts = Counter()
    for row in rows:
        for term in split_terms(str(row.get(field, ""))):
            if term:
                counts[term] += 1
    return [term for term, _ in counts.most_common(limit)]


def average_number(rows: Iterable[Dict], field: str):
    values = []
    for row in rows:
        raw = row.get(field, "")
        try:
            if raw not in {"", None}:
                values.append(float(raw))
        except (TypeError, ValueError):
            continue
    return round(sum(values) / len(values), 2) if values else ""


def playlist_search_phrases(profile: Dict) -> List[str]:
    genres = profile.get("core_genre_tags", [])[:4]
    moods = profile.get("core_mood_tags", [])[:4]
    refs = profile.get("strongest_reference_artists", [])[:4]
    phrases = []
    for genre in genres:
        phrases.append(f"{genre} independent playlist")
    for mood in moods:
        phrases.append(f"{mood} {genres[0] if genres else 'music'} playlist")
    if len(refs) >= 2:
        phrases.append(f"{refs[0]} {refs[1]} playlist")
    if refs and genres:
        phrases.append(f"{refs[0]} {genres[0]} playlist")
    return list(dict.fromkeys(phrases))[:12]


def reference_artist_names(artist_references=None, songs=None, limit: int = 10) -> List[str]:
    refs = [dict(r) for r in artist_references or []]
    refs = [r for r in refs if not r.get("rejected_by_user")]
    refs = sorted(refs, key=lambda r: (bool(r.get("approved_by_user")), float(r.get("confidence_score") or 0)), reverse=True)
    names = [r.get("artist_name", "") for r in refs if r.get("artist_name")]
    if not names and songs:
        names = top_terms(songs, "reference_artists", limit)
    return list(dict.fromkeys(names))[:limit]


def build_artist_sound_profile(songs: List[Dict], profile_name: str = "Artist Sound Profile", artist_references=None) -> Dict:
    songs = [dict(s) for s in songs or []]
    profile = {
        "profile_name": profile_name,
        "song_count": len(songs),
        "track_examples": [s.get("title", "") for s in songs if s.get("title")][:10],
        "average_bpm": average_number(songs, "bpm"),
        "average_danceability": average_number(songs, "danceability"),
        "core_energy": top_terms(songs, "energy", 4),
        "recurring_audio_traits": [],
    }
    for source_field, output_field in TAG_FIELDS.items():
        profile[output_field] = top_terms(songs, source_field, 10)
    profile["strongest_reference_artists"] = reference_artist_names(artist_references, songs, 10)
    profile["reference_artist_policy"] = "Reference artists are discovered or user-confirmed signals, not the primary source of truth."

    traits = []
    for field in ["core_energy", "recurring_instrumentation", "recurring_vocal_styles"]:
        traits.extend(profile.get(field, [])[:4])
    profile["recurring_audio_traits"] = list(dict.fromkeys(traits))[:12]
    profile["playlist_search_phrases"] = playlist_search_phrases(profile)
    profile["chartmetric_mining_targets"] = build_chartmetric_targets(profile)
    return profile
