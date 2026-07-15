#!/usr/bin/env python3
"""Enrich Cyanite seed playlists with Spotify metadata and contact methods."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.database import (  # noqa: E402
    connect,
    get_or_create_curator,
    init_db,
    now,
    upsert_contact_method,
    upsert_playlist,
)
from src.scorer import score_playlist  # noqa: E402
from src.settings import local_data_path  # noqa: E402
from src.spotify_api import SpotifyAPI  # noqa: E402
from src.tavily_enricher import enrich_playlist_with_tavily, tavily_status  # noqa: E402


def load_targets(limit: int = 0, only_missing: bool = True) -> list[dict]:
    where = [
        "exists(select 1 from song_playlist_targets spt where spt.playlist_url=p.url and spt.source='cyanite_seed')"
    ]
    if only_missing:
        where.append(
            "(coalesce(p.followers,0)=0 or not exists(select 1 from contact_methods cm where cm.curator_id=p.curator_id and COALESCE(cm.status,'new') NOT LIKE 'quarantined%'))"
        )
    sql = f"""
        select
            p.id,
            p.name as playlist_name,
            p.url as playlist_url,
            p.followers as follower_count,
            p.related_artists,
            p.spotify_description,
            p.spotify_playlist_id,
            c.display_name as curator_name
        from playlists p
        left join curators c on c.id=p.curator_id
        where {' and '.join(where)}
        order by p.id
    """
    if limit:
        sql += f" limit {int(limit)}"
    with connect() as conn:
        return [dict(row) for row in conn.execute(sql).fetchall()]


def merge_spotify(base: dict, spotify: dict) -> dict:
    merged = dict(base)
    for key in (
        "spotify_playlist_id",
        "playlist_name",
        "playlist_url",
        "follower_count",
        "curator_name",
        "spotify_description",
        "related_artists",
    ):
        if spotify.get(key):
            merged[key] = spotify[key]
    if spotify.get("spotify_tracks"):
        merged["spotify_tracks"] = spotify["spotify_tracks"]
    return merged


def save_enriched_playlist(playlist: dict, contact: dict) -> int:
    methods = contact.get("contact_methods") or []
    contact_score = max([m.get("confidence_score", 0) for m in methods], default=0)
    scored = score_playlist(
        0,
        playlist.get("follower_count", 0),
        playlist.get("last_updated", ""),
        {
            "email": next((m["value"] for m in methods if m.get("type") == "email"), None),
            "instagram": next((m["value"] for m in methods if m.get("type") == "instagram"), None),
            "website": next((m["value"] for m in methods if m.get("type") == "website"), None),
            "submission_page": next((m["value"] for m in methods if m.get("type") == "submission_page"), None),
            "confidence_score": contact_score,
            "submithub_verified": False,
        },
        0,
    )
    notes = json.dumps(
        {
            "source": "cyanite_seed_enrichment",
            "spotify_track_sample_count": len(playlist.get("spotify_tracks") or []),
            "contact_query": contact.get("query", ""),
            "contact_error": contact.get("error", ""),
            "contact_confidence": contact_score,
            "score_breakdown": scored.get("breakdown", {}),
        },
        ensure_ascii=True,
    )
    pid = upsert_playlist(
        {
            "curator": playlist.get("curator_name") or "Unknown Curator",
            "name": playlist.get("playlist_name"),
            "url": playlist.get("playlist_url"),
            "followers": playlist.get("follower_count"),
            "related_artists": playlist.get("related_artists", ""),
            "spotify_description": playlist.get("spotify_description", ""),
            "similarity_score": 0,
            "intersection_score": 0,
            "final_score": scored.get("final_score", 0),
            "priority": scored.get("priority", "new"),
            "spotify_playlist_id": playlist.get("spotify_playlist_id", ""),
            "scoring_notes": notes,
        }
    )
    curator_id = get_or_create_curator(playlist.get("curator_name") or "Unknown Curator")
    for method in methods:
        upsert_contact_method(curator_id, method)
    if playlist.get("related_artists") and playlist.get("playlist_url"):
        with connect() as conn:
            conn.execute(
                """UPDATE song_playlist_targets
                   SET related_artists=?, updated_at=?
                   WHERE playlist_url=? AND source='cyanite_seed'""",
                (playlist.get("related_artists", ""), now(), playlist.get("playlist_url")),
            )
            conn.commit()
    return pid


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--all", action="store_true", help="Re-enrich all Cyanite seed playlists.")
    parser.add_argument("--skip-contacts", action="store_true")
    args = parser.parse_args()

    init_db()
    targets = load_targets(limit=args.limit, only_missing=not args.all)
    spotify = SpotifyAPI()
    if not spotify.configured:
        print("Spotify API is not configured; follower counts cannot be enriched.", file=sys.stderr)
        return 1

    contact_enabled = not args.skip_contacts and tavily_status().get("configured")
    summary = {
        "requested": len(targets),
        "spotify_enriched": 0,
        "contact_searches": 0,
        "contact_methods_saved": 0,
        "errors": [],
    }
    details = []

    for index, target in enumerate(targets, start=1):
        playlist = dict(target)
        try:
            spotify_meta = spotify.normalize_playlist(playlist.get("playlist_url", ""))
        except Exception as exc:
            spotify_meta = {}
            summary["errors"].append(
                {"playlist_url": playlist.get("playlist_url"), "stage": "spotify", "error": str(exc)}
            )
        if spotify_meta:
            playlist = merge_spotify(playlist, spotify_meta)
            summary["spotify_enriched"] += 1

        contact = {"ok": True, "contact_methods": []}
        if contact_enabled:
            contact = enrich_playlist_with_tavily(playlist)
            summary["contact_searches"] += 1
            if not contact.get("ok"):
                summary["errors"].append(
                    {
                        "playlist_url": playlist.get("playlist_url"),
                        "stage": "contact",
                        "error": contact.get("error", ""),
                    }
                )

        save_enriched_playlist(playlist, contact)
        method_count = len(contact.get("contact_methods") or [])
        summary["contact_methods_saved"] += method_count
        details.append(
            {
                "playlist_url": playlist.get("playlist_url"),
                "playlist_name": playlist.get("playlist_name"),
                "curator_name": playlist.get("curator_name"),
                "followers": playlist.get("follower_count", 0),
                "contact_methods": method_count,
            }
        )
        print(
            f"[{index}/{len(targets)}] {playlist.get('playlist_name') or playlist.get('playlist_url')} "
            f"followers={playlist.get('follower_count', 0)} contacts={method_count}",
            flush=True,
        )

    report = {"summary": summary, "details": details}
    local_data_path("cyanite_seed_enrichment_report.json").write_text(
        json.dumps(report, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
