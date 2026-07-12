from typing import Callable, Dict, List

from src.outreach_generator import generate_outreach


INCREDIBLE_FIT_SCORE = 85
DEFAULT_CAMPAIGN_SUBJECT = "Music submission for {playlist_name}"
DEFAULT_CAMPAIGN_BODY = """Hey,

Quick cold email, so I'll keep it short.

I found {playlist_name} and thought one of my tracks might fit.

Spotify link: {song_url}

No worries if it's not right for the playlist.

Thanks,
Nick
Strange Hotels"""


def render_campaign_template(template, playlist_name, song_context=None):
    song_context = song_context or {}
    return str(template or "").replace(
        "{playlist_name}", str(playlist_name or "your playlist")
    ).replace(
        "{song_url}", str(song_context.get("spotify_url") or song_context.get("song_url") or "")
    ).replace(
        "{song_title}", str(song_context.get("title") or song_context.get("song_title") or "")
    ).replace(
        "{artist_name}", str(song_context.get("artist_name") or song_context.get("artist") or "")
    )


def _num(value, default=0.0):
    try:
        return float(value or default)
    except (TypeError, ValueError):
        return default


def _key(value):
    return str(value or "").strip().lower()


def _song_title(item):
    context = item.get("song_context") or {}
    if not isinstance(context, dict):
        context = {}
    return context.get("title") or context.get("song_title") or item.get("song_title") or ""


def _song_artist(item):
    context = item.get("song_context") or {}
    if not isinstance(context, dict):
        context = {}
    return context.get("artist") or context.get("artist_name") or item.get("artist_name") or ""


def _song_url(item):
    context = item.get("song_context") or {}
    if not isinstance(context, dict):
        context = {}
    return context.get("spotify_url") or context.get("song_url") or item.get("song_url") or ""


def _song_context(item):
    context = item.get("song_context") or {}
    context = dict(context) if isinstance(context, dict) else {}
    if not context.get("spotify_url") and item.get("song_url"):
        context["spotify_url"] = item.get("song_url")
    if not context.get("song_url") and item.get("song_url"):
        context["song_url"] = item.get("song_url")
    return context


def _campaign_copy(item):
    context = _song_context(item)
    generated = generate_outreach(
        item,
        {"breakdown": item.get("similarity_breakdown") or item.get("breakdown") or []},
        context,
    )
    return generated


def recommended_channel(item):
    if item.get("submission_page") or item.get("submithub_url"):
        return "Submission"
    if item.get("instagram"):
        return "Instagram"
    if item.get("website"):
        return "Website"
    if item.get("email"):
        return "Email"
    return "Research"


def _channel_sendable(status, channel):
    return status in {"Ready", "Worth considering"} and channel in {"Submission", "Instagram", "Website", "Email"}


def _campaign_choice(item, guard):
    fit = _num(item.get("final_score"))
    if guard and not guard.get("allowed"):
        if fit >= INCREDIBLE_FIT_SCORE:
            return "Worth considering"
        return "Wait"
    return "Ready"


def _contact_route_key(row):
    channel = row.get("recommended_channel")
    if channel == "Email" and row.get("email"):
        return ("email", _key(row.get("email")))
    if channel == "Instagram" and row.get("instagram"):
        return ("instagram", _key(row.get("instagram")).rstrip("/"))
    if channel == "Submission" and row.get("submission_page"):
        return ("submission", _key(row.get("submission_page")).rstrip("/"))
    if channel == "Website" and row.get("website"):
        return ("website", _key(row.get("website")).rstrip("/"))
    return None


def _apply_contact_route_dedupe(rows):
    winners = {}
    for row in sorted(rows, key=lambda item: _num(item.get("fit_score")), reverse=True):
        if row.get("status") == "Wait":
            continue
        route = _contact_route_key(row)
        if not route:
            continue
        if route not in winners:
            winners[route] = row
            continue
        winner = winners[route]
        label = {"email": "email address", "instagram": "Instagram", "submission": "submission link", "website": "website"}.get(route[0], "contact route")
        row["send"] = False
        row["status"] = "Wait"
        row["reason"] = f"Another selected playlist uses the same {label} and has a stronger campaign fit: {winner.get('playlist_name') or 'selected playlist'}."
        row["cooldown_note"] = row["reason"]
    return rows


def prepare_campaign_plan(
    candidates: List[Dict],
    cooldown_days: int = 30,
    guard_fn: Callable[[int, Dict, int], Dict] = None,
    outreach_events: List[Dict] = None,
) -> Dict:
    events_by_playlist = {}
    for event in outreach_events or []:
        events_by_playlist.setdefault(int(event.get("playlist_id") or 0), []).append(event)
    sorted_candidates = sorted(candidates or [], key=lambda item: _num(item.get("final_score")), reverse=True)
    playlist_winners = {}
    playlist_alternates = {}
    for item in sorted_candidates:
        playlist_key = _key(item.get("playlist_url") or item.get("url") or item.get("playlist_name"))
        if not playlist_key:
            continue
        if playlist_key not in playlist_winners:
            playlist_winners[playlist_key] = item
            playlist_alternates[playlist_key] = []
        else:
            playlist_alternates[playlist_key].append(item)

    curator_winners = {}
    rows = []
    held_for_curator = []
    for playlist_key, item in playlist_winners.items():
        curator_key = _key(item.get("curator_name") or item.get("curator") or "Unknown Curator")
        if curator_key in curator_winners:
            held_for_curator.append((item, playlist_key, "Another playlist from this curator has a stronger campaign fit."))
            continue
        curator_winners[curator_key] = item
        song_context = _song_context(item)
        copy = _campaign_copy(item)
        guard = guard_fn(int(item.get("playlist_id") or 0), song_context, cooldown_days) if guard_fn and item.get("playlist_id") else {"allowed": True, "reason": "No saved outreach history for this playlist."}
        status = _campaign_choice(item, guard)
        channel = recommended_channel(item)
        playlist_events = events_by_playlist.get(int(item.get("playlist_id") or 0), [])
        event_types = {event.get("event_type") for event in playlist_events}
        reasons = []
        if item.get("rating_evidence"):
            reasons.extend(item.get("rating_evidence") or [])
        if item.get("matched_descriptors"):
            reasons.append("Matched song tags: " + ", ".join(item.get("matched_descriptors") or []))
        if item.get("discovery_intent_hits"):
            reasons.append("Playlist shows discovery intent: " + ", ".join(item.get("discovery_intent_hits") or []))
        if item.get("submission_ready_hits"):
            reasons.append("Submission-friendly language: " + ", ".join(item.get("submission_ready_hits") or []))
        if item.get("curator_identity_hits"):
            reasons.append("Curator identity signal: " + ", ".join(item.get("curator_identity_hits") or []))
        if item.get("passive_context_hits"):
            reasons.append("Watch passive playlist context: " + ", ".join(item.get("passive_context_hits") or []))
        if guard and not guard.get("allowed"):
            reasons.append(guard.get("reason", "Recent outreach found."))
        rows.append(
            {
                "send": _channel_sendable(status, channel),
                "status": status,
                "playlist_name": item.get("playlist_name") or item.get("name") or "",
                "curator_name": item.get("curator_name") or item.get("curator") or "",
                "selected_song": _song_title(item),
                "artist": _song_artist(item),
                "song_url": _song_url(item),
                "fit_score": round(_num(item.get("final_score")), 2),
                "rating_confidence": _num(item.get("rating_confidence")),
                "playlist_url": item.get("playlist_url") or item.get("url") or "",
                "email": item.get("email") or "",
                "instagram": item.get("instagram") or "",
                "submission_page": item.get("submission_page") or item.get("submithub_url") or "",
                "website": item.get("website") or "",
                "recommended_channel": channel,
                "instagram_opened": "instagram_opened" in event_types or "manual_dm_pasted" in event_types,
                "instagram_dm_pasted": "manual_dm_pasted" in event_types,
                "email_drafted": "drafted" in event_types,
                "submission_sent": "manual_submission_sent" in event_types,
                "email_message": copy.get("email_message") or "",
                "instagram_dm": copy.get("instagram_dm") or "",
                "submission_note": copy.get("submission_note") or "",
                "reason": "; ".join(reasons) or "Best available fit for this playlist.",
                "cooldown_note": "" if guard.get("allowed") else guard.get("reason", ""),
                "alternates": [
                    {
                        "song": _song_title(alt),
                        "artist": _song_artist(alt),
                        "fit_score": round(_num(alt.get("final_score")), 2),
                    }
                    for alt in playlist_alternates.get(playlist_key, [])
                ],
                "raw": item,
            }
        )

    for item, playlist_key, reason in held_for_curator:
        copy = _campaign_copy(item)
        playlist_events = events_by_playlist.get(int(item.get("playlist_id") or 0), [])
        event_types = {event.get("event_type") for event in playlist_events}
        channel = recommended_channel(item)
        rows.append(
            {
                "send": False,
                "status": "Wait",
                "playlist_name": item.get("playlist_name") or item.get("name") or "",
                "curator_name": item.get("curator_name") or item.get("curator") or "",
                "selected_song": _song_title(item),
                "artist": _song_artist(item),
                "song_url": _song_url(item),
                "fit_score": round(_num(item.get("final_score")), 2),
                "rating_confidence": _num(item.get("rating_confidence")),
                "playlist_url": item.get("playlist_url") or item.get("url") or "",
                "email": item.get("email") or "",
                "instagram": item.get("instagram") or "",
                "submission_page": item.get("submission_page") or item.get("submithub_url") or "",
                "website": item.get("website") or "",
                "recommended_channel": channel,
                "instagram_opened": "instagram_opened" in event_types or "manual_dm_pasted" in event_types,
                "instagram_dm_pasted": "manual_dm_pasted" in event_types,
                "email_drafted": "drafted" in event_types,
                "submission_sent": "manual_submission_sent" in event_types,
                "email_message": copy.get("email_message") or "",
                "instagram_dm": copy.get("instagram_dm") or "",
                "submission_note": copy.get("submission_note") or "",
                "reason": reason,
                "cooldown_note": "",
                "alternates": [],
                "raw": item,
            }
        )

    rows = _apply_contact_route_dedupe(rows)
    rows = sorted(rows, key=lambda item: (item["status"] == "Wait", -_num(item.get("fit_score"))))
    return {
        "rows": rows,
        "ready_count": len([row for row in rows if row["status"] == "Ready"]),
        "worth_considering_count": len([row for row in rows if row["status"] == "Worth considering"]),
        "wait_count": len([row for row in rows if row["status"] == "Wait"]),
        "total_candidates": len(candidates or []),
        "unique_playlist_count": len(playlist_winners),
    }
