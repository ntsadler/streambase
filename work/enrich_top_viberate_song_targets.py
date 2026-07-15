#!/usr/bin/env python3
"""Promote and enrich the strongest Viberate/Cyanite song targets."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.database import connect, init_db, upsert_contact_method, upsert_playlist  # noqa: E402
from src.settings import DB_PATH, local_data_path  # noqa: E402
from src.tavily_enricher import enrich_playlist_with_tavily, tavily_status  # noqa: E402


VIBERATE_SOURCES = (
    "viberate_cyanite_seed",
    "viberate_cyanite_seed_mid_tier",
    "viberate_general_auto_attach",
)


def init_contact_tables(db_path=DB_PATH):
    with connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS viberate_contact_enrichment_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                playlist_url TEXT UNIQUE,
                playlist_name TEXT,
                song_title TEXT,
                source TEXT,
                status TEXT DEFAULT 'planned',
                contact_methods_saved INTEGER DEFAULT 0,
                error TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.commit()


def candidate_rows(limit, multi_seed_first=True, db_path=DB_PATH):
    source_marks = ",".join("?" for _ in VIBERATE_SOURCES)
    order_seed = "seed_match_count DESC," if multi_seed_first else ""
    sql = f"""
        WITH viberate_match_summary AS (
            SELECT catalog_song_id, playlist_url,
                   MAX(playlist_name) AS playlist_name,
                   MAX(curator_name) AS curator_name,
                   MAX(follower_count) AS follower_count,
                   COUNT(DISTINCT seed_artist) AS seed_match_count,
                   GROUP_CONCAT(DISTINCT seed_artist) AS cyanite_seed_artists,
                   MIN(seed_rank) AS best_seed_rank,
                   MAX(fit_score) AS fit_score
            FROM viberate_cyanite_playlist_matches
            GROUP BY catalog_song_id, playlist_url
        ),
        ranked AS (
            SELECT spt.song_id, s.title AS song_title, s.artist_name,
                   spt.playlist_url,
                   COALESCE(NULLIF(spt.playlist_name,''), vms.playlist_name) AS playlist_name,
                   COALESCE(vms.curator_name, '') AS curator_name,
                   COALESCE(vms.follower_count, 0) AS follower_count,
                   MAX(COALESCE(spt.fit_score,0), COALESCE(vms.fit_score,0)) AS fit_score,
                   COALESCE(vms.seed_match_count, 0) AS seed_match_count,
                   COALESCE(vms.cyanite_seed_artists, spt.related_artists, '') AS cyanite_seed_artists,
                   COALESCE(vms.best_seed_rank, 0) AS best_seed_rank,
                   spt.source,
                   p.id AS playlist_id,
                   p.curator_id,
                   (SELECT COUNT(*)
                    FROM contact_methods cm
                    WHERE cm.curator_id = p.curator_id
                      AND COALESCE(cm.status,'new') NOT LIKE 'quarantined%') AS contact_count,
                   ROW_NUMBER() OVER (
                       PARTITION BY spt.playlist_url
                       ORDER BY COALESCE(vms.seed_match_count,0) DESC,
                                MAX(COALESCE(spt.fit_score,0), COALESCE(vms.fit_score,0)) DESC
                   ) AS url_rank
            FROM song_playlist_targets spt
            LEFT JOIN songs s ON s.id = spt.song_id
            LEFT JOIN playlists p ON p.url = spt.playlist_url
            LEFT JOIN viberate_contact_enrichment_runs cer ON cer.playlist_url = spt.playlist_url
            LEFT JOIN viberate_match_summary vms
              ON vms.catalog_song_id = spt.song_id AND vms.playlist_url = spt.playlist_url
            LEFT JOIN curators cur ON cur.id = p.curator_id
            WHERE spt.source IN ({source_marks})
              AND COALESCE(spt.playlist_url, '') != ''
              AND cer.playlist_url IS NULL
              AND LOWER(COALESCE(cur.name, '')) NOT IN ('', 'unknown curator', 'spotify')
            GROUP BY spt.song_id, spt.playlist_url
        )
        SELECT *
        FROM ranked
        WHERE url_rank = 1
          AND COALESCE(contact_count, 0) = 0
        ORDER BY {order_seed} fit_score DESC, best_seed_rank ASC, follower_count ASC
        LIMIT ?
    """
    with connect(db_path) as conn:
        rows = conn.execute(sql, (*VIBERATE_SOURCES, int(limit))).fetchall()
    return [dict(row) for row in rows]


def all_saved_candidate_rows(limit, retry_errors=True, db_path=DB_PATH):
    retry_clause = "OR cer.status = 'error'" if retry_errors else ""
    sql = f"""
        WITH viberate_urls AS (
            SELECT DISTINCT playlist_url
            FROM song_playlist_targets
            WHERE source LIKE 'viberate%'
              AND COALESCE(playlist_url, '') != ''
            UNION
            SELECT DISTINCT playlist_url
            FROM viberate_cyanite_playlist_matches
            WHERE COALESCE(playlist_url, '') != ''
        )
        SELECT
            0 AS song_id,
            '' AS song_title,
            '' AS artist_name,
            p.url AS playlist_url,
            p.name AS playlist_name,
            COALESCE(c.display_name, '') AS curator_name,
            COALESCE(p.followers, 0) AS follower_count,
            COALESCE(p.final_score, 0) AS fit_score,
            0 AS seed_match_count,
            COALESCE(p.related_artists, '') AS cyanite_seed_artists,
            0 AS best_seed_rank,
            'saved_playlist' AS source,
            p.id AS playlist_id,
            p.curator_id,
            (SELECT COUNT(*)
             FROM contact_methods cm
             WHERE cm.curator_id = p.curator_id
               AND COALESCE(cm.status,'new') NOT LIKE 'quarantined%') AS contact_count
        FROM playlists p
        JOIN viberate_urls vu ON vu.playlist_url = p.url
        LEFT JOIN curators c ON c.id = p.curator_id
        LEFT JOIN viberate_contact_enrichment_runs cer ON cer.playlist_url = p.url
        WHERE COALESCE(p.url, '') != ''
          AND LOWER(COALESCE(c.name, '')) NOT IN ('', 'unknown curator', 'spotify')
          AND NOT EXISTS (
              SELECT 1 FROM contact_methods cm
              WHERE cm.curator_id = p.curator_id
                AND COALESCE(cm.status,'new') NOT LIKE 'quarantined%'
          )
          AND (cer.playlist_url IS NULL {retry_clause})
        ORDER BY
            COALESCE(p.final_score, 0) DESC,
            COALESCE(p.followers, 0) ASC,
            p.id ASC
        LIMIT ?
    """
    with connect(db_path) as conn:
        rows = conn.execute(sql, (int(limit),)).fetchall()
    return [dict(row) for row in rows]


def playlist_payload(row):
    return {
        "playlist_name": row.get("playlist_name") or "",
        "name": row.get("playlist_name") or "",
        "playlist_url": row.get("playlist_url") or "",
        "url": row.get("playlist_url") or "",
        "curator_name": row.get("curator_name") or "",
        "curator": row.get("curator_name") or "",
        "follower_count": int(row.get("follower_count") or 0),
        "followers": int(row.get("follower_count") or 0),
        "related_artists": row.get("cyanite_seed_artists") or "",
        "final_score": float(row.get("fit_score") or 0),
        "fit_score": float(row.get("fit_score") or 0),
        "scoring_notes": json.dumps(
            {
                "source": row.get("source") or "",
                "song_title": row.get("song_title") or "",
                "seed_match_count": int(row.get("seed_match_count") or 0),
                "cyanite_seed_artists": row.get("cyanite_seed_artists") or "",
                "best_seed_rank": int(row.get("best_seed_rank") or 0),
            },
            ensure_ascii=True,
        ),
    }


def playlist_curator_id(playlist_id, db_path=DB_PATH):
    with connect(db_path) as conn:
        row = conn.execute("SELECT curator_id FROM playlists WHERE id=?", (int(playlist_id),)).fetchone()
    return int(row["curator_id"] or 0) if row else 0


def save_contact_run(row, status, method_count=0, error="", db_path=DB_PATH):
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO viberate_contact_enrichment_runs (
                playlist_url, playlist_name, song_title, source, status,
                contact_methods_saved, error, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT(playlist_url) DO UPDATE SET
                playlist_name=excluded.playlist_name,
                song_title=excluded.song_title,
                source=excluded.source,
                status=excluded.status,
                contact_methods_saved=excluded.contact_methods_saved,
                error=excluded.error,
                updated_at=CURRENT_TIMESTAMP
            """,
            (
                row.get("playlist_url") or "",
                row.get("playlist_name") or "",
                row.get("song_title") or "",
                row.get("source") or "",
                status,
                int(method_count or 0),
                error or "",
            ),
        )
        conn.commit()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--multi-seed-first", action="store_true", default=True)
    parser.add_argument("--all-saved", action="store_true", help="Enrich every saved playlist that lacks contact methods.")
    parser.add_argument("--no-retry-errors", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    init_db(DB_PATH)
    init_contact_tables(DB_PATH)
    if not tavily_status().get("configured"):
        raise SystemExit("TAVILY_API_KEY is not configured.")

    if args.all_saved:
        rows = all_saved_candidate_rows(args.limit, retry_errors=not args.no_retry_errors, db_path=DB_PATH)
    else:
        rows = candidate_rows(args.limit, args.multi_seed_first, DB_PATH)
    summary = {
        "ok": True,
        "requested_limit": int(args.limit),
        "candidate_count": len(rows),
        "promoted_playlists": 0,
        "contact_searches": 0,
        "contact_methods_saved": 0,
        "contactable_playlists": 0,
        "errors": [],
        "examples": [],
    }
    if args.dry_run:
        summary["examples"] = rows[:10]
        print(json.dumps(summary, indent=2))
        return

    for row in rows:
        playlist = playlist_payload(row)
        try:
            playlist_id = upsert_playlist(playlist, DB_PATH)
            summary["promoted_playlists"] += 1 if playlist_id else 0
            contact = enrich_playlist_with_tavily(playlist)
            summary["contact_searches"] += 1
            if not contact.get("ok"):
                save_contact_run(row, "error", 0, contact.get("error", ""), DB_PATH)
                summary["errors"].append(
                    {
                        "playlist": playlist.get("playlist_name"),
                        "url": playlist.get("playlist_url"),
                        "error": contact.get("error", ""),
                    }
                )
                continue
            curator_id = playlist_curator_id(playlist_id, DB_PATH)
            method_count = 0
            for method in contact.get("contact_methods") or []:
                upsert_contact_method(curator_id, method, DB_PATH)
                method_count += 1
            summary["contact_methods_saved"] += method_count
            if method_count:
                summary["contactable_playlists"] += 1
            save_contact_run(row, "contact_found" if method_count else "no_contact", method_count, "", DB_PATH)
            if len(summary["examples"]) < 10:
                summary["examples"].append(
                    {
                        "song": row.get("song_title"),
                        "playlist": playlist.get("playlist_name"),
                        "followers": playlist.get("follower_count"),
                        "fit_score": playlist.get("fit_score"),
                        "seed_match_count": row.get("seed_match_count"),
                        "methods_saved": method_count,
                    }
                )
        except Exception as exc:
            save_contact_run(row, "error", 0, str(exc), DB_PATH)
            summary["errors"].append(
                {
                    "playlist": playlist.get("playlist_name"),
                    "url": playlist.get("playlist_url"),
                    "error": str(exc),
                }
            )

    local_data_path("viberate_contact_enrichment_report.json").write_text(
        json.dumps(summary, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
