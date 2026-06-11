import base64
import os
import re
from typing import Dict, List, Optional

import requests


API_BASE = "https://api.spotify.com/v1"
TOKEN_URL = "https://accounts.spotify.com/api/token"


def extract_playlist_id(url_or_id: str) -> str:
    value = (url_or_id or "").strip()
    if not value:
        return ""
    match = re.search(r"playlist/([A-Za-z0-9]+)", value)
    if match:
        return match.group(1)
    return value.split("?")[0].strip("/")


def extract_track_id(url_or_id: str) -> str:
    value = (url_or_id or "").strip()
    if not value:
        return ""
    match = re.search(r"track/([A-Za-z0-9]+)", value)
    if match:
        return match.group(1)
    return value.split("?")[0].strip("/")


class SpotifyAPI:
    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        timeout: int = 12,
    ):
        self.client_id = client_id or os.getenv("SPOTIFY_CLIENT_ID", "")
        self.client_secret = client_secret or os.getenv("SPOTIFY_CLIENT_SECRET", "")
        self.timeout = timeout
        self._token = ""

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret)

    def _headers(self) -> Dict[str, str]:
        if not self._token:
            self._token = self._fetch_token()
        return {"Authorization": f"Bearer {self._token}"}

    def _fetch_token(self) -> str:
        if not self.configured:
            raise RuntimeError("Spotify API credentials are not configured.")
        raw = f"{self.client_id}:{self.client_secret}".encode("utf-8")
        auth = base64.b64encode(raw).decode("ascii")
        resp = requests.post(
            TOKEN_URL,
            headers={"Authorization": f"Basic {auth}"},
            data={"grant_type": "client_credentials"},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json().get("access_token", "")

    def get_playlist(self, playlist_url_or_id: str) -> Dict:
        playlist_id = extract_playlist_id(playlist_url_or_id)
        if not playlist_id:
            return {}
        fields = (
            "id,name,description,external_urls,followers(total),owner(display_name,id),"
            "tracks.items(track(name,artists(name,id),external_urls,id)),tracks.next"
        )
        resp = requests.get(
            f"{API_BASE}/playlists/{playlist_id}",
            headers=self._headers(),
            params={"fields": fields},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()

    def normalize_playlist(self, playlist_url_or_id: str) -> Dict:
        data = self.get_playlist(playlist_url_or_id)
        if not data:
            return {}
        tracks = []
        for item in data.get("tracks", {}).get("items", []) or []:
            track = item.get("track") or {}
            artists = [a.get("name", "") for a in track.get("artists", []) if a.get("name")]
            tracks.append(
                {
                    "name": track.get("name", ""),
                    "artists": artists,
                    "spotify_url": (track.get("external_urls") or {}).get("spotify", ""),
                }
            )
        return {
            "spotify_playlist_id": data.get("id", ""),
            "playlist_name": data.get("name", ""),
            "playlist_url": (data.get("external_urls") or {}).get("spotify", playlist_url_or_id),
            "follower_count": (data.get("followers") or {}).get("total", 0),
            "curator_name": (data.get("owner") or {}).get("display_name", ""),
            "spotify_description": data.get("description", ""),
            "spotify_tracks": tracks,
            "related_artists": "; ".join(sorted({a for t in tracks for a in t.get("artists", [])})),
        }

    def get_track(self, track_url_or_id: str) -> Dict:
        track_id = extract_track_id(track_url_or_id)
        if not track_id:
            return {}
        resp = requests.get(
            f"{API_BASE}/tracks/{track_id}",
            headers=self._headers(),
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()

    def get_artists(self, artist_ids: List[str]) -> List[Dict]:
        ids = [a for a in artist_ids if a]
        if not ids:
            return []
        resp = requests.get(
            f"{API_BASE}/artists",
            headers=self._headers(),
            params={"ids": ",".join(ids[:50])},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json().get("artists", [])

    def normalize_track(self, track_url_or_id: str) -> Dict:
        data = self.get_track(track_url_or_id)
        if not data:
            return {}
        artists = data.get("artists") or []
        artist_names = [a.get("name", "") for a in artists if a.get("name")]
        artist_meta = self.get_artists([a.get("id", "") for a in artists])
        genres = sorted({g for a in artist_meta for g in a.get("genres", [])})
        album = data.get("album") or {}
        return {
            "spotify_track_id": data.get("id", ""),
            "spotify_url": (data.get("external_urls") or {}).get("spotify", track_url_or_id),
            "title": data.get("name", ""),
            "artist": "; ".join(artist_names),
            "reference_artists": "; ".join(artist_names),
            "descriptors": "; ".join(genres),
            "album": album.get("name", ""),
            "release_date": album.get("release_date", ""),
            "popularity": data.get("popularity", 0),
            "duration_ms": data.get("duration_ms", 0),
            "explicit": data.get("explicit", False),
            "source": "spotify_api",
        }

    def search_playlists(self, query: str, limit: int = 10, market: str = "US") -> List[Dict]:
        if not query:
            return []
        resp = requests.get(
            f"{API_BASE}/search",
            headers=self._headers(),
            params={"q": query, "type": "playlist", "limit": max(1, min(10, int(limit or 10))), "market": market},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        items = (resp.json().get("playlists") or {}).get("items") or []
        playlists = []
        for item in items:
            if not item:
                continue
            owner = item.get("owner") or {}
            playlists.append(
                {
                    "spotify_playlist_id": item.get("id", ""),
                    "playlist_name": item.get("name", ""),
                    "playlist_url": (item.get("external_urls") or {}).get("spotify", ""),
                    "curator_name": owner.get("display_name", ""),
                    "spotify_description": item.get("description", "") or "",
                    "follower_count": 0,
                    "related_artists": "",
                    "search_query": query,
                }
            )
        return playlists

    def search_and_enrich_playlists(self, query: str, limit: int = 10, market: str = "US") -> List[Dict]:
        results = self.search_playlists(query, limit, market)
        enriched = []
        for item in results:
            full = self.normalize_playlist(item.get("playlist_url") or item.get("spotify_playlist_id"))
            enriched.append({**item, **full} if full else item)
        return enriched


def fetch_spotify_playlist(playlist_url_or_id: str) -> Dict:
    client = SpotifyAPI()
    if not client.configured:
        return {}
    try:
        return client.normalize_playlist(playlist_url_or_id)
    except requests.RequestException:
        return {}


def fetch_spotify_track(track_url_or_id: str) -> Dict:
    client = SpotifyAPI()
    if not client.configured:
        return {}
    try:
        return client.normalize_track(track_url_or_id)
    except requests.RequestException:
        return {}


def search_spotify_playlists(queries: List[str], limit_per_query: int = 8, market: str = "US") -> Dict:
    client = SpotifyAPI()
    if not client.configured:
        return {"ok": False, "error": "Spotify API credentials are not configured.", "playlists": []}
    seen = set()
    playlists = []
    try:
        for query in queries:
            for item in client.search_and_enrich_playlists(query, limit_per_query, market):
                url = item.get("playlist_url") or item.get("spotify_playlist_id")
                if not url or url in seen:
                    continue
                seen.add(url)
                playlists.append(item)
        return {"ok": True, "error": "", "playlists": playlists}
    except requests.RequestException as exc:
        return {"ok": False, "error": str(exc), "playlists": playlists}
