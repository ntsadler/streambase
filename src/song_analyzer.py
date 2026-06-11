import wave
from datetime import date
from io import BytesIO
from typing import Dict, List

from src.similarity_engine import split_terms


PLAYLIST_LANES = [
    {
        "lane": "Indie electronic / alt dance",
        "keywords": ["indie", "electronic", "electronica", "dance", "synth", "groove", "house", "nu disco", "mgmt", "lcd soundsystem", "jungle"],
        "pitch": "Target indie dance, alt electronic, and tasteful groove-forward playlists.",
    },
    {
        "lane": "Bedroom pop / chill indie",
        "keywords": ["bedroom", "chill", "soft", "dream", "lofi", "indie pop", "clairo", "men i trust"],
        "pitch": "Look for intimate indie pop, late-night, and soft discovery playlists.",
    },
    {
        "lane": "Alternative rock / modern indie",
        "keywords": ["rock", "guitar", "alternative", "garage", "strokes", "arctic monkeys", "phoenix"],
        "pitch": "Prioritize modern indie rock, alternative discoveries, and guitar-led curator lists.",
    },
    {
        "lane": "Singer-songwriter / emotional indie",
        "keywords": ["songwriter", "lyric", "emotional", "acoustic", "folk", "phoebe", "bon iver"],
        "pitch": "Aim at lyric-forward indie, emotional discovery, and singer-songwriter playlists.",
    },
    {
        "lane": "Pop crossover / upbeat discovery",
        "keywords": ["pop", "hook", "upbeat", "bright", "summer", "radio", "dua lipa", "tame impala"],
        "pitch": "Use pop discovery, upbeat indie, and crossover-friendly playlists.",
    },
    {
        "lane": "Late night / moody electronic",
        "keywords": ["night", "dark", "moody", "ambient", "afterhours", "downtempo", "burial", "four tet"],
        "pitch": "Match with night-drive, moody electronic, and downtempo playlists.",
    },
    {
        "lane": "Fresh finds / independent discovery",
        "keywords": ["new", "fresh", "emerging", "unsigned", "independent", "discovery", "debut"],
        "pitch": "Use independent discovery playlists when the song has clear references but does not fit a narrow genre lane.",
    },
]

NEW_RELEASE_TERMS = [
    "new release",
    "new releases",
    "new music",
    "fresh finds",
    "fresh find",
    "fresh releases",
    "just dropped",
    "latest releases",
    "released this week",
    "new this week",
    "new music friday",
    "release radar",
    "brand new",
    "debut",
]


def _wav_features(file_bytes: bytes) -> Dict:
    try:
        with wave.open(BytesIO(file_bytes), "rb") as w:
            frames = w.getnframes()
            rate = w.getframerate() or 1
            width = w.getsampwidth()
            duration = round(frames / rate, 2)
            sample = w.readframes(min(frames, rate * 20))
            rms = _rms(sample, width) if sample else 0
            peak = float(2 ** (8 * width - 1))
            energy = round(min(100, (rms / peak) * 160), 2) if peak else 0
            return {
                "duration_seconds": duration,
                "sample_rate": rate,
                "channels": w.getnchannels(),
                "energy_estimate": energy,
                "energy_label": "high" if energy >= 60 else "medium" if energy >= 30 else "low",
            }
    except (wave.Error, EOFError):
        return {}


def _rms(sample: bytes, width: int) -> float:
    if width not in {1, 2, 3, 4} or not sample:
        return 0
    values = []
    step = width
    for i in range(0, len(sample) - step + 1, step):
        chunk = sample[i:i + step]
        if width == 1:
            value = chunk[0] - 128
        else:
            value = int.from_bytes(chunk, "little", signed=True)
        values.append(value * value)
    return (sum(values) / len(values)) ** 0.5 if values else 0


def audio_summary(uploaded_file) -> Dict:
    if not uploaded_file:
        return {}
    data = uploaded_file.getvalue()
    name = uploaded_file.name
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    summary = {"file_name": name, "file_type": ext, "size_mb": round(len(data) / 1024 / 1024, 2)}
    if ext == "wav":
        summary.update(_wav_features(data))
    else:
        summary["note"] = "Deep audio features need an audio analysis backend; this pass uses metadata and descriptors for non-WAV files."
    return summary


def _score_lane(text: str, lane: Dict, summary=None, spotify_track=None, cyanite_profile=None) -> Dict:
    summary = summary or {}
    spotify_track = spotify_track or {}
    cyanite_profile = cyanite_profile or {}
    hits = [k for k in lane["keywords"] if k in text]
    score = min(100, 35 + len(hits) * 16) if hits else 20
    energy = summary.get("energy_label", "")
    cyanite_energy = str(cyanite_profile.get("energy", "")).lower()
    popularity = int(spotify_track.get("popularity") or 0)
    duration_ms = int(spotify_track.get("duration_ms") or 0)
    release = release_profile(spotify_track)
    if energy == "high" and any(k in lane["lane"].lower() for k in ["dance", "pop", "rock"]):
        score += 8
        hits.append("high energy")
    if energy == "low" and any(k in lane["lane"].lower() for k in ["chill", "moody", "songwriter"]):
        score += 8
        hits.append("low energy")
    if cyanite_energy in {"high", "energetic"} and any(k in lane["lane"].lower() for k in ["dance", "pop", "rock"]):
        score += 10
        hits.append("cyanite high energy")
    if cyanite_energy in {"low", "calm"} and any(k in lane["lane"].lower() for k in ["chill", "moody", "songwriter"]):
        score += 10
        hits.append("cyanite low energy")
    if popularity and popularity < 45 and "discovery" in lane["lane"].lower() and not release.get("exclude_new_release_playlists"):
        score += 12
        hits.append("emerging artist signal")
    if duration_ms and duration_ms < 150000 and any(k in lane["lane"].lower() for k in ["pop", "discovery"]):
        score += 5
        hits.append("short-form friendly")
    if duration_ms and duration_ms > 300000 and any(k in lane["lane"].lower() for k in ["moody", "electronic"]):
        score += 5
        hits.append("extended track")
    if release.get("exclude_new_release_playlists") and is_new_release_context(lane["lane"] + " " + " ".join(lane["keywords"])):
        score -= 55
        hits.append("old release: avoid new-release lane")
    score = max(0, min(100, score))
    return {**lane, "score": score, "matched_terms": hits, "excluded_for_release_age": release.get("exclude_new_release_playlists") and is_new_release_context(lane["lane"] + " " + " ".join(lane["keywords"]))}


def is_new_release_context(text: str) -> bool:
    hay = (text or "").lower()
    return any(term in hay for term in NEW_RELEASE_TERMS)


def _playlist_match_score(profile_text: str, references: List[str], playlist: Dict, lane_names: List[str], release=None) -> Dict:
    release = release or {}
    hay = " ".join(str(playlist.get(k, "")) for k in ["name", "related_artists", "spotify_description", "curator_name"]).lower()
    shared_refs = [r for r in references if r.lower() and r.lower() in hay]
    lane_hits = [lane for lane in lane_names if any(part in hay for part in lane.lower().split(" / "))]
    descriptor_hits = [term for term in split_terms(profile_text) if len(term) > 3 and term.lower() in hay]
    base = min(100, len(shared_refs) * 24 + len(lane_hits) * 18 + len(descriptor_hits) * 8)
    excluded = release.get("exclude_new_release_playlists") and is_new_release_context(hay)
    if excluded:
        base = 0
    crm_bonus = min(15, float(playlist.get("final_score") or 0) * 0.15)
    return {
        "playlist_name": playlist.get("name", ""),
        "curator_name": playlist.get("curator_name", ""),
        "playlist_url": playlist.get("url", ""),
        "fit_score": round(min(100, base + (0 if excluded else crm_bonus)), 2),
        "excluded_for_release_age": excluded,
        "shared_reference_artists": shared_refs,
        "matched_lanes": lane_hits,
        "matched_descriptors": descriptor_hits[:8],
    }


def merge_song_metadata(title="", artist="", reference_artists="", descriptors="", spotify_track=None):
    spotify_track = spotify_track or {}
    merged = {
        "title": title or spotify_track.get("title", ""),
        "artist": artist or spotify_track.get("artist", ""),
        "reference_artists": "; ".join([x for x in [reference_artists, spotify_track.get("reference_artists", "")] if x]),
        "descriptors": "; ".join([x for x in [descriptors, spotify_track.get("descriptors", ""), spotify_track.get("album", "")] if x]),
    }
    return merged


def merge_reference_track_profile(reference_tracks: List[Dict]) -> Dict:
    tracks = [t for t in reference_tracks or [] if t]
    if not tracks:
        return {}
    artists = []
    descriptors = []
    titles = []
    popularity_values = []
    for track in tracks:
        titles.append(track.get("title", ""))
        artists.extend(split_terms(track.get("artist", "")))
        artists.extend(split_terms(track.get("reference_artists", "")))
        descriptors.extend(split_terms(track.get("descriptors", "")))
        if track.get("album"):
            descriptors.append(track["album"])
        if track.get("popularity") not in {"", None}:
            popularity_values.append(int(track.get("popularity") or 0))
    unique_artists = sorted({a for a in artists if a})
    unique_descriptors = sorted({d for d in descriptors if d})
    avg_popularity = round(sum(popularity_values) / len(popularity_values), 1) if popularity_values else ""
    return {
        "track_count": len(tracks),
        "titles": [t for t in titles if t],
        "reference_artists": "; ".join(unique_artists),
        "descriptors": "; ".join(unique_descriptors),
        "average_popularity": avg_popularity,
    }


def spotify_summary(spotify_track: Dict) -> Dict:
    if not spotify_track:
        return {}
    duration_ms = int(spotify_track.get("duration_ms") or 0)
    return {
        "source": spotify_track.get("source", "spotify"),
        "spotify_track_id": spotify_track.get("spotify_track_id", ""),
        "spotify_url": spotify_track.get("spotify_url", ""),
        "album": spotify_track.get("album", ""),
        "release_date": spotify_track.get("release_date", ""),
        **release_profile(spotify_track),
        "popularity": spotify_track.get("popularity", ""),
        "duration_seconds": round(duration_ms / 1000, 2) if duration_ms else "",
    }


def release_profile(spotify_track: Dict) -> Dict:
    raw = (spotify_track or {}).get("release_date", "")
    if not raw:
        return {"release_age_days": "", "release_age_label": "unknown", "exclude_new_release_playlists": False}
    try:
        parts = [int(p) for p in raw.split("-")]
        if len(parts) == 1:
            released = date(parts[0], 1, 1)
        elif len(parts) == 2:
            released = date(parts[0], parts[1], 1)
        else:
            released = date(parts[0], parts[1], parts[2])
    except (ValueError, TypeError):
        return {"release_age_days": "", "release_age_label": "unknown", "exclude_new_release_playlists": False}
    age_days = max(0, (date.today() - released).days)
    if age_days <= 60:
        label = "current release"
    elif age_days <= 365:
        label = "recent catalog"
    else:
        label = "older catalog"
    return {"release_age_days": age_days, "release_age_label": label, "exclude_new_release_playlists": age_days > 365}


def discovery_searches(top_lanes, song, release=None):
    release = release or {}
    artist = song.get("artist", "")
    refs = song.get("reference_artists", [])
    ref_text = " ".join(refs[:3])
    searches = []
    for lane in top_lanes:
        if release.get("exclude_new_release_playlists") and is_new_release_context(lane["lane"]):
            continue
        lane_name = lane["lane"].split(" / ")[0]
        qualifier = "evergreen spotify playlist curator submission" if release.get("exclude_new_release_playlists") else "spotify playlist curator submission"
        searches.append(
            {
                "lane": lane["lane"],
                "search_query": " ".join([lane_name, ref_text, artist, qualifier]).strip(),
            }
        )
    return searches


def analyze_song_fit(uploaded_file, title="", artist="", reference_artists="", descriptors="", saved_playlists=None, spotify_track=None, reference_tracks=None, cyanite_profile=None) -> Dict:
    summary = audio_summary(uploaded_file)
    reference_profile = merge_reference_track_profile(reference_tracks or [])
    cyanite_profile = cyanite_profile or {}
    if reference_profile:
        reference_artists = "; ".join([x for x in [reference_artists, reference_profile.get("reference_artists", "")] if x])
        descriptors = "; ".join([x for x in [descriptors, reference_profile.get("descriptors", "")] if x])
    if cyanite_profile:
        descriptors = "; ".join([x for x in [descriptors, cyanite_profile.get("descriptors", "")] if x])
    merged = merge_song_metadata(title, artist, reference_artists, descriptors, spotify_track)
    release = release_profile(spotify_track or {})
    references = split_terms(merged["reference_artists"])
    text = " ".join([merged["title"], merged["artist"], merged["reference_artists"], merged["descriptors"], summary.get("file_name", ""), summary.get("energy_label", ""), str(cyanite_profile.get("energy", "")), str(cyanite_profile.get("voice", ""))]).lower()
    lanes = sorted([_score_lane(text, lane, summary, spotify_track, cyanite_profile) for lane in PLAYLIST_LANES], key=lambda x: x["score"], reverse=True)
    top_lanes = [lane for lane in lanes if not lane.get("excluded_for_release_age")][:3]
    matches = []
    for playlist in saved_playlists or []:
        match = _playlist_match_score(";".join([merged["descriptors"], merged["reference_artists"]]), references, playlist, [l["lane"] for l in top_lanes], release)
        if match["fit_score"] > 0 and not match.get("excluded_for_release_age"):
            matches.append(match)
    matches = sorted(matches, key=lambda x: x["fit_score"], reverse=True)[:12]
    return {
        "song": {"title": merged["title"], "artist": merged["artist"], "reference_artists": references, "descriptors": merged["descriptors"]},
        "audio_summary": summary,
        "spotify_summary": spotify_summary(spotify_track or {}),
        "reference_track_summary": reference_profile,
        "cyanite_summary": cyanite_profile,
        "release_guidance": {
            **release,
            "message": "Older catalog track: Streambase will avoid playlists explicitly focused on new releases." if release.get("exclude_new_release_playlists") else "Release age is compatible with new-release and evergreen playlist pitching.",
        },
        "recommended_playlist_lanes": top_lanes,
        "saved_playlist_matches": matches,
        "discovery_searches": discovery_searches(top_lanes, {"artist": merged["artist"], "reference_artists": references}, release),
        "next_steps": [
            "Add 3-8 accurate reference artists or reference songs before outreach.",
            "Use Cyanite audio tags when available for sound-based playlist fit.",
            "Use the top lane names as search terms for new playlist discovery.",
            "Prioritize saved playlist matches with both reference artist overlap and existing curator contact data.",
        ],
    }


def score_spotify_playlist_candidates(song_fit: Dict, candidates: List[Dict], existing_playlists=None) -> List[Dict]:
    song = song_fit.get("song") or {}
    release = song_fit.get("release_guidance") or {}
    references = song.get("reference_artists") or []
    descriptors = song.get("descriptors", "")
    lane_names = [lane.get("lane", "") for lane in song_fit.get("recommended_playlist_lanes", [])]
    existing_urls = {p.get("url") for p in (existing_playlists or []) if p.get("url")}
    scored = []
    for candidate in candidates:
        url = candidate.get("playlist_url", "")
        playlist_like = {
            "name": candidate.get("playlist_name", ""),
            "url": url,
            "related_artists": candidate.get("related_artists", ""),
            "spotify_description": candidate.get("spotify_description", ""),
            "curator_name": candidate.get("curator_name", ""),
            "final_score": 0,
        }
        match = _playlist_match_score(";".join([descriptors, candidate.get("search_query", "")]), references, playlist_like, lane_names, release)
        if match.get("excluded_for_release_age"):
            continue
        follower_count = int(candidate.get("follower_count") or 0)
        follower_bonus = 10 if 500 <= follower_count <= 100000 else 4 if follower_count > 0 else 0
        query_bonus = 8 if candidate.get("search_query") else 0
        fit_score = min(100, match.get("fit_score", 0) + follower_bonus + query_bonus)
        scored.append(
            {
                **candidate,
                "candidate_fit_score": round(fit_score, 2),
                "already_in_crm": url in existing_urls,
                "shared_reference_artists": match.get("shared_reference_artists", []),
                "matched_lanes": match.get("matched_lanes", []),
                "matched_descriptors": match.get("matched_descriptors", []),
                "excluded_for_release_age": False,
            }
        )
    return sorted(scored, key=lambda x: (x.get("already_in_crm", False), -float(x.get("candidate_fit_score") or 0), -int(x.get("follower_count") or 0)))
