#!/usr/bin/env python3
"""Attach older/general Viberate-mined playlists to the best matching catalog songs."""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.database import connect, init_db, save_song_playlist_target  # noqa: E402
from src.settings import DB_PATH, local_data_path  # noqa: E402


STOP = {
    "and", "are", "best", "curator", "curators", "for", "from", "hits", "low",
    "music", "new", "old", "playlist", "playlists", "release", "releases",
    "songs", "spotify", "submissions", "the", "this", "under", "with",
}
GENERIC = {
    "00", "01", "02", "03", "04", "05", "06", "07", "08", "09", "10",
    "100", "1000", "500", "followers", "small", "micro", "niche",
}
MOOD_ONLY = {
    "calm", "chill", "happy", "sad", "dark", "sexy", "romantic",
    "uplifting", "energetic", "ethereal",
}
STYLE_TERMS = {
    "r&b", "lo-fi", "psychedelic", "electronic", "alternative", "shoegaze",
    "garage", "funk", "soul", "disco", "dance", "house", "indie", "pop",
    "rock", "dream pop", "bedroom pop", "indie pop", "alt pop", "garage rock",
    "psych rock", "new wave", "deep house",
}
ALIASES = {
    "rnb": "r&b",
    "rn": "r&b",
    "lofi": "lo-fi",
    "lo": "lo-fi",
    "fi": "lo-fi",
    "psych": "psychedelic",
    "electro": "electronic",
    "alt": "alternative",
    "bedroom": "bedroom pop",
    "dream": "dream pop",
    "shoegaze": "shoegaze",
    "garage": "garage",
    "funk": "funk",
    "soul": "soul",
    "disco": "disco",
    "dance": "dance",
    "house": "house",
    "indie": "indie",
    "pop": "pop",
    "rock": "rock",
    "chill": "chill",
    "calm": "calm",
    "happy": "happy",
    "sad": "sad",
    "dark": "dark",
    "sexy": "sexy",
    "romantic": "romantic",
    "uplifting": "uplifting",
    "energetic": "energetic",
    "ethereal": "ethereal",
}


def terms(value):
    out = set()
    text = str(value or "").lower().replace("&", " r&b ")
    for token in re.findall(r"[a-z0-9&+-]+", text):
        token = token.strip("-+")
        if len(token) < 3 or token in STOP or token in GENERIC:
            continue
        out.add(ALIASES.get(token, token))
    for phrase in ["dream pop", "bedroom pop", "indie pop", "alt pop", "garage rock", "psych rock", "new wave", "deep house"]:
        if phrase in text:
            out.add(phrase)
    return out


def song_rows(db_path=DB_PATH):
    with connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT s.id, s.title, s.artist_name, s.release_status,
                   sap.genre_tags, sap.mood_tags, sap.energy, sap.instrumentation,
                   sap.vocal_style, sap.reference_artists, sap.recommended_playlist_categories,
                   sap.recommended_chartmetric_targets, sap.notes
            FROM songs s
            LEFT JOIN song_audio_profiles sap ON sap.song_id=s.id
            ORDER BY s.id
            """
        ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["term_set"] = terms(
            " ".join(
                str(item.get(key) or "")
                for key in [
                    "title", "genre_tags", "mood_tags", "energy", "instrumentation",
                    "vocal_style", "reference_artists", "recommended_playlist_categories",
                    "recommended_chartmetric_targets", "notes",
                ]
            )
        )
        result.append(item)
    return result


def playlist_rows(db_path=DB_PATH):
    with connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT mp.playlist_url,
                   MAX(mp.playlist_name) AS playlist_name,
                   MAX(mp.curator_name) AS curator_name,
                   MAX(mp.follower_count) AS follower_count,
                   MAX(mp.spotify_description) AS spotify_description,
                   MAX(mp.fit_score) AS fit_score,
                   MAX(mp.fit_reason) AS fit_reason,
                   GROUP_CONCAT(DISTINCT mp.query) AS queries,
                   GROUP_CONCAT(DISTINCT mp.matched_terms) AS matched_terms,
                   GROUP_CONCAT(DISTINCT mp.best_song_titles) AS best_song_titles
            FROM mined_playlists mp
            WHERE mp.source='viberate'
              AND COALESCE(mp.playlist_url,'')!=''
              AND mp.playlist_url NOT IN (
                  SELECT playlist_url FROM song_playlist_targets WHERE COALESCE(playlist_url,'')!=''
              )
            GROUP BY mp.playlist_url
            """
        ).fetchall()
    return [dict(row) for row in rows]


def score(song, playlist):
    playlist_text = " ".join(
        str(playlist.get(key) or "")
        for key in [
            "playlist_name", "curator_name", "spotify_description", "fit_reason",
            "queries", "matched_terms", "best_song_titles",
        ]
    )
    p_terms = terms(playlist_text)
    overlap = song["term_set"] & p_terms
    core_overlap = overlap - {"indie", "pop", "rock", "alternative", "music"}
    style_overlap = overlap & STYLE_TERMS
    mood_overlap = overlap & MOOD_ONLY
    base = 42
    score_value = base + len(style_overlap) * 9 + len(core_overlap) * 5 + len(mood_overlap) * 2
    if not style_overlap:
        score_value -= 18
    if str(song.get("title") or "").lower() in str(playlist.get("best_song_titles") or "").lower():
        score_value += 12
    if "new release" in p_terms and str(song.get("release_status") or "").lower() not in {"released", "catalog"}:
        score_value += 4
    try:
        followers = int(playlist.get("follower_count") or 0)
    except (TypeError, ValueError):
        followers = 0
    if 50 <= followers <= 10000:
        score_value += 6
    elif followers > 0:
        score_value += 2
    score_value = max(0, min(100, score_value))
    return score_value, sorted(overlap), sorted(core_overlap)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--threshold", type=float, default=70)
    parser.add_argument("--max-songs-per-playlist", type=int, default=3)
    parser.add_argument("--margin", type=float, default=8)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    init_db(DB_PATH)
    songs = song_rows(DB_PATH)
    playlists = playlist_rows(DB_PATH)
    summary = {
        "ok": True,
        "playlist_candidates": len(playlists),
        "attached_rows": 0,
        "attached_playlists": 0,
        "skipped_playlists": 0,
        "examples": [],
    }
    for playlist in playlists:
        ranked = []
        for song in songs:
            score_value, overlap, core_overlap = score(song, playlist)
            if score_value >= float(args.threshold):
                ranked.append((score_value, song, overlap, core_overlap))
        ranked.sort(key=lambda item: item[0], reverse=True)
        if ranked:
            top = ranked[0][0]
            chosen = [
                item for item in ranked[: int(args.max_songs_per_playlist)]
                if item[0] >= top - float(args.margin)
            ]
        else:
            chosen = []
        if not chosen:
            summary["skipped_playlists"] += 1
            continue
        summary["attached_playlists"] += 1
        for score_value, song, overlap, core_overlap in chosen:
            payload = {
                "playlist_name": playlist.get("playlist_name") or "",
                "playlist_url": playlist.get("playlist_url") or "",
                "curator_name": playlist.get("curator_name") or "",
                "follower_count": int(playlist.get("follower_count") or 0),
                "fit_score": round(score_value, 2),
                "related_artists": playlist.get("matched_terms") or playlist.get("queries") or "",
                "raw": {
                    "source": "general_viberate_song_attachment",
                    "overlap_terms": overlap,
                    "core_overlap_terms": core_overlap,
                    "original_fit_score": playlist.get("fit_score"),
                    "queries": playlist.get("queries"),
                    "fit_reason": playlist.get("fit_reason"),
                },
            }
            notes = f"Auto-attached general Viberate playlist; matched {', '.join(core_overlap or overlap)}"
            if not args.dry_run:
                save_song_playlist_target(
                    int(song["id"]),
                    payload,
                    source="viberate_general_auto_attach",
                    fit_score=round(score_value, 2),
                    status="target",
                    notes=notes,
                    db_path=DB_PATH,
                )
            summary["attached_rows"] += 1
            if len(summary["examples"]) < 20:
                summary["examples"].append(
                    {
                        "song": song.get("title"),
                        "playlist": playlist.get("playlist_name"),
                        "score": round(score_value, 2),
                        "terms": core_overlap or overlap,
                    }
                )
    if not args.dry_run:
        local_data_path("general_viberate_auto_attach_report.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
