#!/usr/bin/env python3
"""Second-pass contact enrichment for saved playlists with named curators."""
import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.database import connect, init_db, upsert_contact_method  # noqa: E402
from src.settings import DB_PATH, local_data_path  # noqa: E402
from src.web_enricher import enrich_contact_info  # noqa: E402


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def init_table(db_path=DB_PATH):
    with connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS fallback_contact_enrichment_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                playlist_id INTEGER UNIQUE,
                playlist_url TEXT,
                playlist_name TEXT,
                curator_id INTEGER,
                curator_name TEXT,
                status TEXT DEFAULT 'planned',
                contact_methods_saved INTEGER DEFAULT 0,
                error TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.commit()


def candidate_rows(limit, retry_errors=False, db_path=DB_PATH):
    retry_clause = "OR f.status='error'" if retry_errors else ""
    sql = f"""
        SELECT p.id AS playlist_id, p.name AS playlist_name, p.url AS playlist_url,
               p.followers, p.final_score, p.curator_id, c.display_name AS curator_name
        FROM playlists p
        JOIN curators c ON c.id=p.curator_id
        LEFT JOIN fallback_contact_enrichment_runs f ON f.playlist_id=p.id
        WHERE COALESCE(p.url,'')!=''
          AND lower(c.name) NOT IN ('unknown curator','spotify')
          AND NOT EXISTS (
              SELECT 1 FROM contact_methods cm WHERE cm.curator_id=p.curator_id
          )
          AND (f.playlist_id IS NULL {retry_clause})
        ORDER BY COALESCE(p.final_score,0) DESC, COALESCE(p.followers,0) ASC, p.id ASC
        LIMIT ?
    """
    with connect(db_path) as conn:
        rows = conn.execute(sql, (int(limit),)).fetchall()
    return [dict(row) for row in rows]


def save_run(row, status, method_count=0, error="", db_path=DB_PATH):
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO fallback_contact_enrichment_runs (
                playlist_id, playlist_url, playlist_name, curator_id, curator_name,
                status, contact_methods_saved, error, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT(playlist_id) DO UPDATE SET
                playlist_url=excluded.playlist_url,
                playlist_name=excluded.playlist_name,
                curator_id=excluded.curator_id,
                curator_name=excluded.curator_name,
                status=excluded.status,
                contact_methods_saved=excluded.contact_methods_saved,
                error=excluded.error,
                updated_at=CURRENT_TIMESTAMP
            """,
            (
                int(row.get("playlist_id") or 0),
                row.get("playlist_url") or "",
                row.get("playlist_name") or "",
                int(row.get("curator_id") or 0),
                row.get("curator_name") or "",
                status,
                int(method_count or 0),
                error or "",
            ),
        )
        conn.commit()


def log_event(path, payload):
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"timestamp": utc_now(), **payload}, sort_keys=True) + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--sleep", type=float, default=2.0)
    parser.add_argument("--retry-errors", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    init_db(DB_PATH)
    init_table(DB_PATH)
    rows = candidate_rows(args.limit, args.retry_errors, DB_PATH)
    summary = {
        "ok": True,
        "candidate_count": len(rows),
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

    log_path = local_data_path("fallback_contact_enrichment.jsonl")
    for row in rows:
        try:
            contact = enrich_contact_info(row.get("playlist_name") or "", row.get("curator_name") or "", row.get("playlist_url") or "")
            summary["contact_searches"] += 1
            method_count = 0
            for method in contact.get("contact_methods") or []:
                upsert_contact_method(int(row.get("curator_id") or 0), method, DB_PATH)
                method_count += 1
            summary["contact_methods_saved"] += method_count
            if method_count:
                summary["contactable_playlists"] += 1
            save_run(row, "contact_found" if method_count else "no_contact", method_count, "", DB_PATH)
            item = {
                "playlist": row.get("playlist_name"),
                "curator": row.get("curator_name"),
                "methods_saved": method_count,
            }
            if len(summary["examples"]) < 10:
                summary["examples"].append(item)
            log_event(log_path, {"event": "playlist_finished", **item})
        except Exception as exc:
            message = str(exc)
            save_run(row, "error", 0, message, DB_PATH)
            summary["errors"].append({"playlist": row.get("playlist_name"), "error": message})
        if args.sleep:
            time.sleep(float(args.sleep))

    local_data_path("fallback_contact_enrichment_report.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
