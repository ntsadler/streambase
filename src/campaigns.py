from typing import Callable, Dict, List


INCREDIBLE_FIT_SCORE = 85


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


def _campaign_choice(item, guard):
    fit = _num(item.get("final_score"))
    if guard and not guard.get("allowed"):
        if fit >= INCREDIBLE_FIT_SCORE:
            return "Worth considering"
        return "Wait"
    return "Ready"


def prepare_campaign_plan(
    candidates: List[Dict],
    cooldown_days: int = 30,
    guard_fn: Callable[[int, Dict, int], Dict] = None,
) -> Dict:
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
        song_context = item.get("song_context") if isinstance(item.get("song_context"), dict) else {}
        guard = guard_fn(int(item.get("playlist_id") or 0), song_context, cooldown_days) if guard_fn and item.get("playlist_id") else {"allowed": True, "reason": "No saved outreach history for this playlist."}
        status = _campaign_choice(item, guard)
        reasons = []
        if item.get("rating_evidence"):
            reasons.extend(item.get("rating_evidence") or [])
        if item.get("matched_descriptors"):
            reasons.append("Matched song tags: " + ", ".join(item.get("matched_descriptors") or []))
        if item.get("discovery_intent_hits"):
            reasons.append("Playlist shows discovery intent: " + ", ".join(item.get("discovery_intent_hits") or []))
        if guard and not guard.get("allowed"):
            reasons.append(guard.get("reason", "Recent outreach found."))
        rows.append(
            {
                "send": status in {"Ready", "Worth considering"},
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
                "email_message": item.get("email_message") or "",
                "instagram_dm": item.get("instagram_dm") or "",
                "submission_note": item.get("submission_note") or "",
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
                "email_message": item.get("email_message") or "",
                "instagram_dm": item.get("instagram_dm") or "",
                "submission_note": item.get("submission_note") or "",
                "reason": reason,
                "cooldown_note": "",
                "alternates": [],
                "raw": item,
            }
        )

    rows = sorted(rows, key=lambda item: (item["status"] == "Wait", -_num(item.get("fit_score"))))
    return {
        "rows": rows,
        "ready_count": len([row for row in rows if row["status"] == "Ready"]),
        "worth_considering_count": len([row for row in rows if row["status"] == "Worth considering"]),
        "wait_count": len([row for row in rows if row["status"] == "Wait"]),
        "total_candidates": len(candidates or []),
        "unique_playlist_count": len(playlist_winners),
    }
