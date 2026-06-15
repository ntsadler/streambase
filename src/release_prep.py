from pathlib import Path
from typing import Dict, List

from src.audio_analysis import clean_filename, title_from_filename
from src.mining_targets import build_chartmetric_targets
from src.settings import project_data_path
from src.similarity_engine import split_terms


RELEASE_STATUSES = ["unreleased", "scheduled", "released"]
CAMPAIGN_STATUSES = ["needs_profile", "profile_ready", "mining_ready", "campaign_draft", "approved", "launched"]


def release_prep_upload_dir() -> Path:
    path = project_data_path("audio_uploads")
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_release_prep_upload(uploaded_file) -> Dict:
    if not uploaded_file:
        return {"ok": False, "error": "Choose a WAV or MP3 file first."}
    name = clean_filename(getattr(uploaded_file, "name", "") or "song")
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext not in {"wav", "mp3"}:
        return {"ok": False, "error": "Release Prep Library accepts WAV and MP3 files."}
    path = release_prep_upload_dir() / name
    path.write_bytes(uploaded_file.getvalue())
    return {
        "ok": True,
        "title": title_from_filename(name),
        "file_path": str(path),
        "release_status": "unreleased",
        "planned_release_date": "",
        "campaign_status": "needs_profile",
        "analysis_source": "manual",
        "notes": "Manual profile pending.",
    }


def song_profile_from_row(song: Dict) -> Dict:
    genres = split_terms(song.get("genre_tags", ""))
    moods = split_terms(song.get("mood_tags", ""))
    refs = split_terms(song.get("reference_artists", ""))
    categories = split_terms(song.get("recommended_playlist_categories", ""))
    profile = {
        "core_genre_tags": genres,
        "core_mood_tags": moods,
        "strongest_reference_artists": refs,
        "track_examples": [song.get("title", "")] if song.get("title") else [],
        "recurring_audio_traits": split_terms("; ".join([song.get("energy", ""), song.get("instrumentation", ""), song.get("vocal_style", "")])),
        "playlist_search_phrases": categories,
    }
    profile["chartmetric_mining_targets"] = build_chartmetric_targets(profile)
    return profile


def infer_playlist_categories(song: Dict) -> List[str]:
    genres = split_terms(song.get("genre_tags", ""))[:4]
    moods = split_terms(song.get("mood_tags", ""))[:4]
    energy = split_terms(song.get("energy", ""))[:2]
    categories = []
    for genre in genres:
        categories.append(f"{genre} discovery")
    for mood in moods:
        categories.append(f"{mood} playlist")
    for item in energy:
        categories.append(f"{item} independent playlist")
    return list(dict.fromkeys(categories))[:10]


def campaign_readiness(song: Dict) -> str:
    if not song.get("genre_tags") or not song.get("mood_tags"):
        return "needs_profile"
    if not song.get("reference_artists"):
        return "profile_ready"
    if not song.get("recommended_chartmetric_targets"):
        return "mining_ready"
    return song.get("campaign_status") or "campaign_draft"


def build_campaign_brief(song: Dict) -> Dict:
    profile = song_profile_from_row(song)
    targets = profile["chartmetric_mining_targets"]
    categories = split_terms(song.get("recommended_playlist_categories", "")) or infer_playlist_categories(song)
    refs = profile.get("strongest_reference_artists", [])
    genres = profile.get("core_genre_tags", [])
    moods = profile.get("core_mood_tags", [])
    traits = profile.get("recurring_audio_traits", [])
    angle_parts = []
    if moods:
        angle_parts.append(moods[0])
    if genres:
        angle_parts.append(genres[0])
    if traits:
        angle_parts.append(traits[0])
    outreach_angle = "Position as " + ", ".join(angle_parts) + " for independent discovery playlists." if angle_parts else "Position around the strongest manually verified song traits."
    return {
        "song_title": song.get("title", ""),
        "release_status": song.get("release_status", "unreleased"),
        "planned_release_date": song.get("planned_release_date", ""),
        "song_dna_summary": {
            "genres": genres,
            "moods": moods,
            "energy": song.get("energy", ""),
            "bpm": song.get("bpm", ""),
            "key": song.get("key", ""),
            "danceability": song.get("danceability", ""),
            "instrumentation": split_terms(song.get("instrumentation", "")),
            "vocal_style": song.get("vocal_style", ""),
            "lyrical_theme_notes": song.get("lyrical_theme_notes", ""),
        },
        "best_reference_artists": refs,
        "best_playlist_keywords": categories,
        "best_chartmetric_mining_queries": targets.get("chartmetric_queries", []),
        "ideal_playlist_follower_range": targets.get("playlist_follower_range", {}),
        "exclusion_rules": targets.get("playlist_exclusion_rules", []),
        "suggested_outreach_angle": outreach_angle,
        "copy_direction": {
            "email": f"Lead with the song's {', '.join(moods[:2] + genres[:2]) or 'clearest'} lane and mention why it fits the curator's playlist.",
            "instagram_dm": "Keep it short: one sentence of context, one Spotify/private link, one fit reason.",
            "submission_page": "Use the most concrete genre/mood tags and avoid overexplaining.",
        },
        "chartmetric_mining_targets": targets,
    }
