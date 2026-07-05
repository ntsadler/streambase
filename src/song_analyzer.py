import wave
from datetime import date
from io import BytesIO
from typing import Dict, List

from src.similarity_engine import split_terms


PLAYLIST_LANES = [
    {
        "lane": "Indie electronic / alt dance",
        "keywords": ["indie", "electronic", "electronica", "dance", "synth", "groove", "house", "nu disco", "rhythmic", "analog"],
        "pitch": "Target indie dance, alt electronic, and tasteful groove-forward playlists.",
    },
    {
        "lane": "Bedroom pop / chill indie",
        "keywords": ["bedroom", "chill", "soft", "dream", "lofi", "indie pop", "intimate", "hazy"],
        "pitch": "Look for intimate indie pop, late-night, and soft discovery playlists.",
    },
    {
        "lane": "Alternative rock / modern indie",
        "keywords": ["rock", "guitar", "alternative", "garage", "angular", "band", "drums"],
        "pitch": "Prioritize modern indie rock, alternative discoveries, and guitar-led curator lists.",
    },
    {
        "lane": "Singer-songwriter / emotional indie",
        "keywords": ["songwriter", "lyric", "emotional", "acoustic", "folk", "introspective", "vocal"],
        "pitch": "Aim at lyric-forward indie, emotional discovery, and singer-songwriter playlists.",
    },
    {
        "lane": "Pop crossover / upbeat discovery",
        "keywords": ["pop", "hook", "upbeat", "bright", "summer", "radio", "melodic", "catchy"],
        "pitch": "Use pop discovery, upbeat indie, and crossover-friendly playlists.",
    },
    {
        "lane": "Late night / moody electronic",
        "keywords": ["night", "dark", "moody", "ambient", "afterhours", "downtempo", "textural", "atmospheric"],
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

DISCOVERY_INTENT_TERMS = [
    "emerging artists",
    "independent artists",
    "artist discovery",
    "unsigned",
    "new artists",
    "up and coming",
    "rising artists",
    "fresh finds",
    "discover weekly",
]

SUBMISSION_READY_TERMS = [
    "submit",
    "submissions",
    "submission",
    "send your music",
    "send music",
    "submit music",
    "for submissions",
    "playlist submission",
    "dm submissions",
]

CURATOR_IDENTITY_TERMS = [
    "curated by",
    "curator",
    "blog",
    "radio",
    "records",
    "collective",
    "magazine",
    "label",
]

THROWBACK_TERMS = [
    "throwback",
    "old school",
    "oldschool",
    "classic hits",
    "classics",
    "nostalgia",
    "y2k",
    "2000s",
    "90s",
    "80s",
    "70s",
    "60s",
]

PASSIVE_CONTEXT_TERMS = [
    "background",
    "study",
    "sleep",
    "focus",
    "coffee shop",
    "dinner",
    "relaxing music",
    "hits",
    "top hits",
    "viral hits",
    "best songs",
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


def discovery_intent_hits(text: str) -> List[str]:
    hay = (text or "").lower()
    return [term for term in DISCOVERY_INTENT_TERMS if term in hay]


def throwback_context_hits(text: str) -> List[str]:
    hay = (text or "").lower()
    return [term for term in THROWBACK_TERMS if term in hay]


def submission_ready_hits(text: str) -> List[str]:
    hay = (text or "").lower()
    return [term for term in SUBMISSION_READY_TERMS if term in hay]


def curator_identity_hits(text: str) -> List[str]:
    hay = (text or "").lower()
    return [term for term in CURATOR_IDENTITY_TERMS if term in hay]


def passive_context_hits(text: str) -> List[str]:
    hay = (text or "").lower()
    return [term for term in PASSIVE_CONTEXT_TERMS if term in hay]


def playlist_targeting_profile(text: str) -> Dict:
    hay = text or ""
    discovery_hits = discovery_intent_hits(hay)
    submission_hits = submission_ready_hits(hay)
    curator_hits = curator_identity_hits(hay)
    throwback_hits = throwback_context_hits(hay)
    passive_hits = passive_context_hits(hay)
    quality_score = len(discovery_hits) * 16 + len(submission_hits) * 14 + len(curator_hits) * 8
    risk_score = len(throwback_hits) * 22 + len(passive_hits) * 10
    return {
        "discovery_intent_hits": discovery_hits,
        "submission_ready_hits": submission_hits,
        "curator_identity_hits": curator_hits,
        "throwback_context_hits": throwback_hits,
        "passive_context_hits": passive_hits,
        "curator_target_score": max(-60, min(60, quality_score - risk_score)),
    }


def _playlist_match_score(profile_text: str, references: List[str], playlist: Dict, lane_names: List[str], release=None) -> Dict:
    release = release or {}
    hay = " ".join(str(playlist.get(k, "")) for k in ["name", "related_artists", "spotify_description", "curator_name"]).lower()
    shared_refs = [r for r in references if r.lower() and r.lower() in hay]
    lane_hits = [lane for lane in lane_names if any(part in hay for part in lane.lower().split(" / "))]
    descriptor_hits = [term for term in split_terms(profile_text) if len(term) > 3 and term.lower() in hay]
    targeting = playlist_targeting_profile(hay)
    discovery_hits = targeting["discovery_intent_hits"]
    throwback_hits = targeting["throwback_context_hits"]
    base = min(
        100,
        len(shared_refs) * 24
        + len(lane_hits) * 18
        + len(descriptor_hits) * 8
        + len(discovery_hits) * 12
        + targeting["curator_target_score"],
    )
    excluded = release.get("exclude_new_release_playlists") and is_new_release_context(hay)
    if excluded:
        base = 0
    if throwback_hits and not discovery_hits:
        base = max(0, base - 55)
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
        "discovery_intent_hits": discovery_hits,
        "throwback_context_hits": throwback_hits,
        "submission_ready_hits": targeting["submission_ready_hits"],
        "curator_identity_hits": targeting["curator_identity_hits"],
        "passive_context_hits": targeting["passive_context_hits"],
        "curator_target_score": targeting["curator_target_score"],
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


def preferred_catalog_title(uploaded_title="", analysis_title="", spotify_track=None, release_status="unreleased"):
    spotify_track = spotify_track or {}
    spotify_title = str(spotify_track.get("title") or "").strip()
    if str(release_status or "").lower() in {"released", "already_released"} and spotify_title:
        return spotify_title
    return str(analysis_title or uploaded_title or spotify_title or "").strip()


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


def cyanite_evidence_terms(cyanite_profile: Dict) -> List[str]:
    profile = cyanite_profile or {}
    raw_terms = []
    for key in ["genres", "moods", "instruments", "keywords"]:
        value = profile.get(key)
        if isinstance(value, list):
            raw_terms.extend(value)
        elif value:
            raw_terms.extend(split_terms(str(value)))
    for key in ["voice", "movement", "energy", "musical_era", "descriptors"]:
        if profile.get(key):
            raw_terms.extend(split_terms(str(profile.get(key))))
    seen = set()
    terms = []
    for term in raw_terms:
        clean = " ".join(str(term).split())
        key = clean.lower()
        if clean and key not in seen:
            seen.add(key)
            terms.append(clean)
    return terms


def cyanite_search_terms(cyanite_profile: Dict) -> List[str]:
    profile = cyanite_profile or {}
    prioritized = []
    for key, limit in [("genres", 3), ("moods", 2), ("instruments", 2)]:
        value = profile.get(key)
        terms = value if isinstance(value, list) else split_terms(str(value or ""))
        prioritized.extend([term for term in terms if term][:limit])
    if profile.get("voice"):
        prioritized.extend(split_terms(str(profile.get("voice")))[:1])
    if profile.get("movement"):
        prioritized.extend(split_terms(str(profile.get("movement")))[:1])
    seen = set()
    terms = []
    for term in prioritized:
        clean = " ".join(str(term).split())
        key = clean.lower()
        if clean and key not in seen:
            seen.add(key)
            terms.append(clean)
    return terms[:7]


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
    context = (spotify_track or {}).get("release_context", "")
    if context == "new_release":
        return {"release_age_days": 0, "release_age_label": "new release", "exclude_new_release_playlists": False}
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
    descriptors = split_terms(song.get("descriptors", ""))
    if song.get("cyanite_summary"):
        cyanite_terms = cyanite_search_terms(song.get("cyanite_summary", {}))
        descriptors = cyanite_terms + [term for term in descriptors if term.lower() not in {x.lower() for x in cyanite_terms}]
    descriptors = [term for term in descriptors if len(term) > 2]
    searches = []
    for lane in top_lanes:
        if release.get("exclude_new_release_playlists") and is_new_release_context(lane["lane"]):
            continue
        lane_name = lane["lane"].split(" / ")[0]
        lane_terms = split_terms(lane_name)
        matched_terms = [term for term in lane.get("matched_terms", []) if len(term) > 2]
        audio_terms = []
        for term in descriptors + matched_terms + lane_terms:
            clean = " ".join(str(term).split())
            if clean and clean.lower() not in {t.lower() for t in audio_terms}:
                audio_terms.append(clean)
        audio_core = audio_terms[:4] + lane_terms[:1]
        if release.get("exclude_new_release_playlists"):
            audio_core.append("evergreen")
        for intent in ["emerging artists", "independent artists", "playlist submissions", "submit music"]:
            query_terms = audio_core + [intent, "playlist"]
            query = " ".join(query_terms[:8]).strip()
            if query:
                searches.append(
                    {
                        "lane": lane["lane"],
                        "source": "emerging_artist_discovery",
                        "search_query": query,
                    }
                )
        searches.append(
            {
                "lane": lane["lane"],
                "source": "audio_discovery",
                "search_query": " ".join((audio_core + ["artist discovery", "playlist"])[:8]).strip(),
            }
        )
    return searches


def suggest_reference_song_searches(song=None, descriptors="", cyanite_profile=None, top_lanes=None) -> List[Dict]:
    song = song or {}
    cyanite_profile = cyanite_profile or {}
    refs = song.get("reference_artists", [])
    if isinstance(refs, str):
        refs = split_terms(refs)
    artist = song.get("artist", "")
    descriptor_terms = split_terms("; ".join([descriptors, cyanite_profile.get("descriptors", "")]))
    descriptor_terms = [term for term in descriptor_terms if len(term) > 2][:6]
    lanes = top_lanes or []
    lane_terms = [lane.get("lane", "").split(" / ")[0] for lane in lanes if lane.get("lane")]
    queries = []

    for ref in refs[:3]:
        seed = " ".join([ref, "similar", "song", "spotify"]).strip()
        queries.append({"source": "reference_artist", "search_query": seed})

    if descriptor_terms:
        queries.append({"source": "descriptors", "search_query": " ".join(descriptor_terms[:4] + ["song", "spotify"])})

    for lane in lane_terms[:2]:
        query = " ".join([lane] + descriptor_terms[:2] + ["song"]).strip()
        queries.append({"source": "playlist_lane", "search_query": query})

    if artist and descriptor_terms:
        queries.append({"source": "artist_context", "search_query": " ".join([artist] + descriptor_terms[:3])})

    seen = set()
    out = []
    for item in queries:
        query = " ".join(item["search_query"].split())
        if query and query.lower() not in seen:
            seen.add(query.lower())
            out.append({**item, "search_query": query})
    return out[:6]


def analyze_song_fit(uploaded_file, title="", artist="", reference_artists="", descriptors="", saved_playlists=None, spotify_track=None, reference_tracks=None, cyanite_profile=None) -> Dict:
    summary = audio_summary(uploaded_file)
    reference_profile = merge_reference_track_profile(reference_tracks or [])
    cyanite_profile = cyanite_profile or {}
    cyanite_terms = cyanite_evidence_terms(cyanite_profile)
    if reference_profile:
        reference_artists = "; ".join([x for x in [reference_artists, reference_profile.get("reference_artists", "")] if x])
        descriptors = "; ".join([x for x in [descriptors, reference_profile.get("descriptors", "")] if x])
    if cyanite_terms:
        descriptors = "; ".join([x for x in [descriptors, "; ".join(cyanite_terms)] if x])
    merged = merge_song_metadata(title, artist, reference_artists, descriptors, spotify_track)
    release = release_profile(spotify_track or {})
    references = split_terms(merged["reference_artists"])
    text = " ".join([merged["title"], merged["artist"], merged["reference_artists"], merged["descriptors"], summary.get("file_name", ""), summary.get("energy_label", ""), " ".join(cyanite_terms)]).lower()
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
        "cyanite_evidence_terms": cyanite_terms,
        "release_guidance": {
            **release,
            "message": "Older catalog track: Streambase will avoid playlists explicitly focused on new releases." if release.get("exclude_new_release_playlists") else "Release age is compatible with new-release and evergreen playlist pitching.",
        },
        "recommended_playlist_lanes": top_lanes,
        "saved_playlist_matches": matches,
        "discovery_searches": discovery_searches(top_lanes, {"artist": merged["artist"], "reference_artists": references, "descriptors": merged["descriptors"], "cyanite_summary": cyanite_profile}, release),
        "reference_song_searches": suggest_reference_song_searches(
            {"artist": merged["artist"], "reference_artists": references},
            merged["descriptors"],
            cyanite_profile,
            top_lanes,
        ),
        "next_steps": [
            "Review the Cyanite Song DNA and correct any obvious tag mistakes before outreach.",
            "Use the generated playlist searches to find sound-aligned Spotify playlists.",
            "Treat reference artists as discovered evidence or user corrections, not the starting point.",
            "Prioritize playlist matches with strong audio fit, healthy Spotify signals, and verified contact or submission paths.",
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
        if match.get("throwback_context_hits") and not match.get("discovery_intent_hits"):
            continue
        follower_count = int(candidate.get("follower_count") or 0)
        follower_bonus = 10 if 500 <= follower_count <= 75000 else 5 if 75_000 < follower_count <= 150_000 else 4 if follower_count > 0 else 0
        query_bonus = 8 if candidate.get("search_query") else 0
        discovery_bonus = 10 if match.get("discovery_intent_hits") else 0
        submission_bonus = 10 if match.get("submission_ready_hits") else 0
        identity_bonus = 5 if match.get("curator_identity_hits") else 0
        passive_penalty = min(20, len(match.get("passive_context_hits") or []) * 8)
        fit_score = min(100, max(0, match.get("fit_score", 0) + follower_bonus + query_bonus + discovery_bonus + submission_bonus + identity_bonus - passive_penalty))
        scored.append(
            {
                **candidate,
                "candidate_fit_score": round(fit_score, 2),
                "already_in_crm": url in existing_urls,
                "shared_reference_artists": match.get("shared_reference_artists", []),
                "matched_lanes": match.get("matched_lanes", []),
                "matched_descriptors": match.get("matched_descriptors", []),
                "discovery_intent_hits": match.get("discovery_intent_hits", []),
                "throwback_context_hits": match.get("throwback_context_hits", []),
                "submission_ready_hits": match.get("submission_ready_hits", []),
                "curator_identity_hits": match.get("curator_identity_hits", []),
                "passive_context_hits": match.get("passive_context_hits", []),
                "curator_target_score": match.get("curator_target_score", 0),
                "excluded_for_release_age": False,
            }
        )
    return sorted(scored, key=lambda x: (x.get("already_in_crm", False), -float(x.get("candidate_fit_score") or 0), -int(x.get("follower_count") or 0)))
