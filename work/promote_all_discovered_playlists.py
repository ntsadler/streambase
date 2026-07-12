#!/usr/bin/env python3
"""Promote every discovered playlist candidate into the main Streambase CRM."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.database import connect, init_db, upsert_playlist  # noqa: E402
from src.settings import DB_PATH, local_data_path  # noqa: E402


def discovered_rows(db_path=DB_PATH):
    sql = """
        WITH target_summary AS (
            SELECT playlist_url,
                   MAX(playlist_name) AS playlist_name,
                   MAX(fit_score) AS fit_score,
                   MAX(source) AS source,
                   MAX(related_artists) AS related_artists
            FROM song_playlist_targets
            WHERE COALESCE(playlist_url, '') != ''
            GROUP BY playlist_url
        ),
        match_summary AS (
            SELECT playlist_url,
                   MAX(playlist_name) AS playlist_name,
                   MAX(curator_name) AS curator_name,
                   MAX(follower_count) AS follower_count,
                   MAX(fit_score) AS fit_score,
                   GROUP_CONCAT(DISTINCT seed_artist) AS seed_artists
            FROM viberate_cyanite_playlist_matches
            WHERE COALESCE(playlist_url, '') != ''
            GROUP BY playlist_url
        ),
        mined_summary AS (
            SELECT playlist_url,
                   MAX(playlist_name) AS playlist_name,
                   MAX(curator_name) AS curator_name,
                   MAX(follower_count) AS follower_count,
                   MAX(spotify_description) AS spotify_description,
                   MAX(fit_score) AS fit_score,
                   MAX(fit_reason) AS fit_reason,
                   GROUP_CONCAT(DISTINCT query) AS queries,
                   MAX(source) AS source
            FROM mined_playlists
            WHERE COALESCE(playlist_url, '') != ''
            GROUP BY playlist_url
        ),
        all_urls AS (
            SELECT playlist_url FROM target_summary
            UNION
            SELECT playlist_url FROM mined_summary
        )
        SELECT u.playlist_url,
               COALESCE(NULLIF(ms.playlist_name, ''), NULLIF(ts.playlist_name, ''), NULLIF(mn.playlist_name, '')) AS playlist_name,
               COALESCE(NULLIF(ms.curator_name, ''), NULLIF(mn.curator_name, '')) AS curator_name,
               COALESCE(ms.follower_count, mn.follower_count, 0) AS follower_count,
               COALESCE(NULLIF(mn.spotify_description, ''), '') AS spotify_description,
               MAX(COALESCE(ts.fit_score, 0), COALESCE(ms.fit_score, 0), COALESCE(mn.fit_score, 0)) AS final_score,
               COALESCE(NULLIF(ms.seed_artists, ''), NULLIF(ts.related_artists, ''), NULLIF(mn.queries, '')) AS related_artists,
               COALESCE(NULLIF(ts.source, ''), NULLIF(mn.source, ''), 'discovered') AS source,
               COALESCE(NULLIF(mn.fit_reason, ''), '') AS fit_reason
        FROM all_urls u
        LEFT JOIN target_summary ts ON ts.playlist_url=u.playlist_url
        LEFT JOIN match_summary ms ON ms.playlist_url=u.playlist_url
        LEFT JOIN mined_summary mn ON mn.playlist_url=u.playlist_url
        LEFT JOIN playlists p ON p.url=u.playlist_url
        WHERE p.url IS NULL
        ORDER BY final_score DESC, follower_count ASC, playlist_name
    """
    with connect(db_path) as conn:
        rows = conn.execute(sql).fetchall()
    return [dict(row) for row in rows]


def payload(row):
    notes = {
        "source": row.get("source") or "discovered",
        "fit_reason": row.get("fit_reason") or "",
        "promoted_from": "all_discovered_playlists",
    }
    return {
        "playlist_name": row.get("playlist_name") or "Untitled playlist",
        "name": row.get("playlist_name") or "Untitled playlist",
        "playlist_url": row.get("playlist_url") or "",
        "url": row.get("playlist_url") or "",
        "curator_name": row.get("curator_name") or "Unknown Curator",
        "curator": row.get("curator_name") or "Unknown Curator",
        "follower_count": int(row.get("follower_count") or 0),
        "followers": int(row.get("follower_count") or 0),
        "spotify_description": row.get("spotify_description") or "",
        "related_artists": row.get("related_artists") or "",
        "final_score": float(row.get("final_score") or 0),
        "similarity_score": float(row.get("final_score") or 0),
        "priority": "promoted",
        "scoring_notes": json.dumps(notes, ensure_ascii=True),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    init_db(DB_PATH)
    rows = discovered_rows(DB_PATH)
    summary = {
        "ok": True,
        "candidate_count": len(rows),
        "promoted_count": 0,
        "examples": rows[:10],
    }
    if args.dry_run:
        print(json.dumps(summary, indent=2))
        return
    for row in rows:
        if upsert_playlist(payload(row), DB_PATH):
            summary["promoted_count"] += 1
    local_data_path("promote_all_discovered_playlists_report.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
