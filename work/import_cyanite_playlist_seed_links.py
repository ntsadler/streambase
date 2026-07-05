#!/usr/bin/env python3
"""Import Cyanite playlist matching links into Streambase."""

from __future__ import annotations

import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.database import import_song_seed_playlists, init_db  # noqa: E402


INPUT_PATH = Path("/tmp/cyanite_playlist_seed_links.json")
SPOTIFY_OEMBED = "https://open.spotify.com/oembed?url="


def fetch_oembed(playlist_url: str, cache: dict[str, dict]) -> dict:
    if playlist_url in cache:
        return cache[playlist_url]
    endpoint = SPOTIFY_OEMBED + urllib.parse.quote(playlist_url, safe="")
    try:
        request = urllib.request.Request(
            endpoint,
            headers={"User-Agent": "Streambase Cyanite Seed Importer/1.0"},
        )
        with urllib.request.urlopen(request, timeout=12) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:  # Keep imports moving if Spotify has a hiccup.
        payload = {"error": str(exc)}
    cache[playlist_url] = payload
    time.sleep(0.1)
    return payload


def playlist_name_from_oembed(payload: dict, fallback: str) -> str:
    title = (payload.get("title") or "").strip()
    return title or fallback


def main() -> int:
    if not INPUT_PATH.exists():
        print(f"Missing input file: {INPUT_PATH}", file=sys.stderr)
        return 1

    init_db()
    data = json.loads(INPUT_PATH.read_text())
    cache: dict[str, dict] = {}
    imported = []

    for song in data.get("songs", []):
        playlists = []
        for item in song.get("playlists", []):
            playlist_url = item.get("playlist_url") or ""
            if not playlist_url:
                continue
            oembed = fetch_oembed(playlist_url, cache)
            name = playlist_name_from_oembed(
                oembed,
                f"Cyanite playlist seed {item.get('rank') or ''}".strip(),
            )
            playlist_id = item.get("spotify_playlist_id") or playlist_url.rstrip("/").split("/")[-1]
            playlists.append(
                {
                    "playlist_name": name,
                    "name": name,
                    "playlist_url": playlist_url,
                    "url": playlist_url,
                    "curator_name": "Spotify",
                    "curator": "Spotify",
                    "spotify_playlist_id": playlist_id,
                    "followers": 0,
                    "related_artists": "",
                    "fit_score": 85,
                    "candidate_fit_score": 85,
                    "spotify_description": "",
                    "notes": "Imported from Cyanite playlist matching",
                    "raw_json": {
                        "source": "cyanite_playlist_matching",
                        "cyanite_track_id": song.get("cyanite_track_id"),
                        "streambase_song_id": song.get("song_id"),
                        "streambase_song_title": song.get("title"),
                        "cyanite_rank": item.get("rank"),
                        "spotify_oembed": oembed,
                    },
                }
            )

        saved = import_song_seed_playlists(
            song.get("song_id"),
            playlists,
            source="cyanite_seed",
        )
        imported.append(
            {
                "song_id": song.get("song_id"),
                "title": song.get("title"),
                "requested": len(playlists),
                "saved": len(saved),
            }
        )

    total = sum(row["saved"] for row in imported)
    print(json.dumps({"songs": len(imported), "saved_targets": total, "details": imported}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
