#!/usr/bin/env python3
"""Build a first-round pitch allocation: one curator, one song, one playlist."""
import argparse
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.database import connect, init_db, now  # noqa: E402
from src.settings import DB_PATH, local_data_path  # noqa: E402


ROUND_NAME = "round_1"


def init_table(db_path=DB_PATH):
    with connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS pitch_round_allocations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                round_name TEXT,
                song_id INTEGER,
                song_title TEXT,
                playlist_id INTEGER,
                playlist_url TEXT,
                playlist_name TEXT,
                curator_id INTEGER,
                curator_name TEXT,
                selected INTEGER DEFAULT 0,
                rank_for_curator INTEGER DEFAULT 0,
                allocation_score REAL DEFAULT 0,
                fit_score REAL DEFAULT 0,
                contact_route TEXT,
                contact_value TEXT,
                follower_count INTEGER DEFAULT 0,
                hold_reason TEXT,
                source TEXT,
                details_json TEXT,
                created_at TEXT,
                updated_at TEXT,
                UNIQUE(round_name, song_id, playlist_id)
            )
            """
        )
        conn.commit()


def contact_select_sql(contact_type):
    return f"""
        (SELECT value FROM contact_methods
         WHERE curator_id=p.curator_id
           AND type='{contact_type}'
           AND COALESCE(status,'new') NOT LIKE 'quarantined%'
         ORDER BY confidence_score DESC, created_at DESC LIMIT 1)
    """


def candidate_rows(min_fit, include_unknown=False, db_path=DB_PATH):
    unknown_clause = "" if include_unknown else "AND lower(c.name) NOT IN ('unknown curator','spotify')"
    sql = f"""
        SELECT
            spt.id AS song_target_id,
            spt.song_id,
            s.title AS song_title,
            s.artist_name,
            spt.playlist_url,
            COALESCE(NULLIF(spt.playlist_name,''), p.name) AS playlist_name,
            spt.fit_score,
            spt.source,
            spt.notes,
            p.id AS playlist_id,
            p.followers AS follower_count,
            p.final_score AS playlist_score,
            p.curator_id,
            c.display_name AS curator_name,
            {contact_select_sql('submission_page')} AS submission_page,
            {contact_select_sql('email')} AS email,
            {contact_select_sql('instagram')} AS instagram,
            {contact_select_sql('website')} AS website,
            {contact_select_sql('link_hub')} AS link_hub,
            EXISTS (
                SELECT 1 FROM email_queue q
                WHERE q.playlist_id=p.id
                  AND q.status IN ('pending_approval','approved','sent')
            ) AS has_email_queue,
            EXISTS (
                SELECT 1 FROM outreach_events oe
                WHERE oe.playlist_id=p.id
            ) AS has_outreach_event
        FROM song_playlist_targets spt
        JOIN playlists p ON p.url=spt.playlist_url
        JOIN curators c ON c.id=p.curator_id
        LEFT JOIN songs s ON s.id=spt.song_id
        WHERE COALESCE(spt.playlist_url,'')!=''
          AND COALESCE(spt.fit_score,0) >= ?
          AND p.id IS NOT NULL
          AND EXISTS (
              SELECT 1 FROM contact_methods cm
              WHERE cm.curator_id=p.curator_id
                AND cm.type IN ('submission_page','email','instagram','website','link_hub')
                AND COALESCE(cm.status,'new') NOT LIKE 'quarantined%'
          )
          AND NOT EXISTS (
              SELECT 1 FROM email_queue q
              WHERE q.playlist_id=p.id
                AND q.status IN ('pending_approval','approved','sent')
          )
          AND NOT EXISTS (
              SELECT 1 FROM outreach_events oe
              WHERE oe.playlist_id=p.id
                AND oe.event_type IN ('sent','manual_submission_sent','manual_dm_pasted','instagram_opened')
          )
          {unknown_clause}
    """
    with connect(db_path) as conn:
        rows = conn.execute(sql, (float(min_fit),)).fetchall()
    return [dict(row) for row in rows]


def contact_route(row):
    if row.get("submission_page"):
        return "submission_page", row.get("submission_page"), 35
    if row.get("email"):
        return "email", row.get("email"), 32
    if row.get("instagram"):
        return "instagram", row.get("instagram"), 24
    if row.get("website"):
        return "website", row.get("website"), 14
    if row.get("link_hub"):
        return "link_hub", row.get("link_hub"), 12
    return "research", "", 0


def follower_bonus(value):
    try:
        followers = int(value or 0)
    except (TypeError, ValueError):
        followers = 0
    if 50 <= followers <= 1000:
        return 12
    if 1001 <= followers <= 5000:
        return 10
    if 5001 <= followers <= 10000:
        return 7
    if 10001 <= followers <= 50000:
        return 3
    return 0


def score(row):
    route, value, route_bonus = contact_route(row)
    fit = float(row.get("fit_score") or 0)
    playlist_score = float(row.get("playlist_score") or 0)
    value_score = fit * 0.72 + min(playlist_score, 100) * 0.1 + route_bonus + follower_bonus(row.get("follower_count"))
    if row.get("source") == "viberate_general_auto_attach":
        value_score -= 4
    if row.get("has_email_queue") or row.get("has_outreach_event"):
        value_score -= 100
    return round(max(0, min(100, value_score)), 2), route, value


def build_allocations(rows):
    scored = []
    for row in rows:
        allocation_score, route, value = score(row)
        if allocation_score <= 0:
            continue
        scored.append({**row, "allocation_score": allocation_score, "contact_route": route, "contact_value": value})

    # First resolve multiple songs for the same playlist, then one playlist per curator.
    playlist_winners = {}
    playlist_alternates = {}
    for row in sorted(scored, key=lambda r: (-float(r["allocation_score"]), -float(r.get("fit_score") or 0), int(r.get("playlist_id") or 0))):
        key = int(row.get("playlist_id") or 0)
        if key not in playlist_winners:
            playlist_winners[key] = row
            playlist_alternates[key] = []
        else:
            playlist_alternates[key].append(row)

    curator_groups = {}
    for row in playlist_winners.values():
        curator_groups.setdefault(int(row.get("curator_id") or 0), []).append(row)

    allocations = []
    for curator_id, group in curator_groups.items():
        ranked = sorted(group, key=lambda r: (-float(r["allocation_score"]), -float(r.get("fit_score") or 0), int(r.get("playlist_id") or 0)))
        winner = ranked[0]
        for index, row in enumerate(ranked, start=1):
            selected = row is winner
            reason = "" if selected else f"Held: curator already has round-one winner ({winner.get('song_title')} -> {winner.get('playlist_name')})."
            details = {
                "artist_name": row.get("artist_name") or "",
                "playlist_score": row.get("playlist_score") or 0,
                "song_target_id": row.get("song_target_id") or 0,
                "source": row.get("source") or "",
                "playlist_alternates": [
                    {
                        "song_id": alt.get("song_id"),
                        "song_title": alt.get("song_title"),
                        "fit_score": alt.get("fit_score"),
                        "allocation_score": alt.get("allocation_score"),
                    }
                    for alt in playlist_alternates.get(int(row.get("playlist_id") or 0), [])
                ],
            }
            allocations.append(
                {
                    **row,
                    "selected": 1 if selected else 0,
                    "rank_for_curator": index,
                    "hold_reason": reason,
                    "details": details,
                }
            )
    return sorted(allocations, key=lambda r: (0 if r["selected"] else 1, -float(r["allocation_score"]), r.get("curator_name") or ""))


def save_allocations(rows, round_name=ROUND_NAME, db_path=DB_PATH):
    timestamp = now()
    with connect(db_path) as conn:
        conn.execute("DELETE FROM pitch_round_allocations WHERE round_name=?", (round_name,))
        for row in rows:
            conn.execute(
                """
                INSERT INTO pitch_round_allocations (
                    round_name, song_id, song_title, playlist_id, playlist_url, playlist_name,
                    curator_id, curator_name, selected, rank_for_curator, allocation_score,
                    fit_score, contact_route, contact_value, follower_count, hold_reason,
                    source, details_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    round_name,
                    int(row.get("song_id") or 0),
                    row.get("song_title") or "",
                    int(row.get("playlist_id") or 0),
                    row.get("playlist_url") or "",
                    row.get("playlist_name") or "",
                    int(row.get("curator_id") or 0),
                    row.get("curator_name") or "",
                    int(row.get("selected") or 0),
                    int(row.get("rank_for_curator") or 0),
                    float(row.get("allocation_score") or 0),
                    float(row.get("fit_score") or 0),
                    row.get("contact_route") or "",
                    row.get("contact_value") or "",
                    int(row.get("follower_count") or 0),
                    row.get("hold_reason") or "",
                    row.get("source") or "",
                    json.dumps(row.get("details") or {}, ensure_ascii=True),
                    timestamp,
                    timestamp,
                ),
            )
        conn.commit()
    return len(rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--round-name", default=ROUND_NAME)
    parser.add_argument("--min-fit", type=float, default=70)
    parser.add_argument("--include-unknown-curators", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    init_db(DB_PATH)
    init_table(DB_PATH)
    candidates = candidate_rows(args.min_fit, args.include_unknown_curators, DB_PATH)
    allocations = build_allocations(candidates)
    selected = [row for row in allocations if row.get("selected")]
    held = [row for row in allocations if not row.get("selected")]
    summary = {
        "ok": True,
        "round_name": args.round_name,
        "candidate_count": len(candidates),
        "allocation_count": len(allocations),
        "selected_count": len(selected),
        "held_count": len(held),
        "selected_by_channel": {},
        "examples": [
            {
                "song": row.get("song_title"),
                "playlist": row.get("playlist_name"),
                "curator": row.get("curator_name"),
                "score": row.get("allocation_score"),
                "fit": row.get("fit_score"),
                "route": row.get("contact_route"),
                "followers": row.get("follower_count"),
            }
            for row in selected[:20]
        ],
    }
    for row in selected:
        summary["selected_by_channel"][row.get("contact_route") or ""] = summary["selected_by_channel"].get(row.get("contact_route") or "", 0) + 1
    if not args.dry_run:
        save_allocations(allocations, args.round_name, DB_PATH)
        local_data_path("round_one_pitch_allocations_report.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
