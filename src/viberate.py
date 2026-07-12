import os
import time
from typing import Dict, List, Optional

import requests

from src.env import load_local_env

load_local_env()


class ViberateAPI:
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: int = 12,
    ):
        self.api_key = api_key or os.getenv("VIBERATE_API_KEY", "")
        self.base_url = (base_url or os.getenv("VIBERATE_API_BASE_URL", "https://data.viberate.com/api/v1")).rstrip("/")
        try:
            self.timeout = int(os.getenv("VIBERATE_TIMEOUT_SECONDS", timeout))
        except (TypeError, ValueError):
            self.timeout = timeout
        self.last_status_code = 0
        self.last_response_headers = {}

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def _headers(self) -> Dict[str, str]:
        auth_header = os.getenv("VIBERATE_AUTH_HEADER", "Access-Key")
        auth_prefix = os.getenv("VIBERATE_AUTH_PREFIX", "")
        value = f"{auth_prefix} {self.api_key}".strip() if auth_prefix else self.api_key
        return {auth_header: value, "Accept": "application/json"}

    def get(self, path: str, params: Optional[Dict] = None) -> Dict:
        if not self.configured:
            raise RuntimeError("Viberate API key is not configured.")
        resp = requests.get(
            f"{self.base_url}/{path.lstrip('/')}",
            headers=self._headers(),
            params=params or {},
            timeout=self.timeout,
        )
        self.last_status_code = resp.status_code
        self.last_response_headers = dict(resp.headers or {})
        resp.raise_for_status()
        return resp.json()

    def search_playlists(self, query: str, limit: int = 25, offset: int = 0) -> Dict:
        path = os.getenv("VIBERATE_PLAYLIST_SEARCH_PATH", "playlist/search")
        return self.get(path, {"q": query, "limit": min(int(limit or 20), 20), "offset": offset})

    def search_artists(self, query: str, limit: int = 1, offset: int = 0) -> Dict:
        return self.get("artist/search", {"q": query, "limit": min(int(limit or 20), 20), "offset": offset})

    def get_artist_spotify_playlists(
        self,
        artist_uuid: str,
        limit: int = 20,
        offset: int = 0,
        sort: str = "followers",
        order: str = "asc",
    ) -> Dict:
        return self.get(
            f"artist/{artist_uuid}/spotify/playlists",
            {"limit": min(int(limit or 20), 20), "offset": offset, "sort": sort, "order": order},
        )

    def search_playlists_by_artist(self, artist_name: str, limit: int = 25, sleep_seconds: float = 0.0) -> Dict:
        return self.search_artist_playlist_page(artist_name, limit=limit, offset=0, sleep_seconds=sleep_seconds)

    def search_artist_playlist_page(
        self,
        artist_name: str,
        limit: int = 25,
        offset: int = 0,
        sleep_seconds: float = 0.0,
    ) -> Dict:
        artist_response = self.search_artists(artist_name, limit=1)
        artist = next(iter(artist_response.get("data") or []), {})
        artist_uuid = artist.get("uuid") or ""
        if not artist_uuid:
            return {"data": [], "artist_search": artist_response}
        if sleep_seconds:
            time.sleep(sleep_seconds)
        playlist_response = self.get_artist_spotify_playlists(artist_uuid, limit=limit, offset=offset, sort="followers", order="asc")
        playlist_data = playlist_response.get("data") or {}
        playlists = playlist_data.get("data") if isinstance(playlist_data, dict) else playlist_data
        if isinstance(playlists, list):
            for playlist in playlists:
                playlist.setdefault("curator", "")
                playlist.setdefault("source_artist_name", artist.get("name") or artist_name)
                playlist.setdefault("source_artist_uuid", artist_uuid)
        return {**playlist_response, "data": playlists or [], "artist": artist}

    def chart_playlists(self, params: Optional[Dict] = None, limit: int = 20, offset: int = 0) -> Dict:
        query = dict(params or {})
        query["limit"] = min(int(limit or 20), 20)
        query["offset"] = offset
        return self.get("playlist/viberate/chart", query)

    def get_playlist_snapshot(self, playlist_id: str) -> Dict:
        path = os.getenv("VIBERATE_PLAYLIST_DETAIL_PATH", "playlist/{id}/details").format(id=playlist_id)
        return self.get(path)


def normalize_viberate_playlist(raw: Dict, query: str = "") -> Dict:
    raw = raw or {}
    playlist_id = (
        raw.get("id")
        or raw.get("uuid")
        or raw.get("playlist_id")
        or raw.get("viberate_playlist_id")
        or raw.get("spotify_playlist_id")
        or ""
    )
    name = raw.get("name") or raw.get("playlist_name") or raw.get("title") or ""
    external_id = raw.get("external_id") or raw.get("spotify_id") or ""
    url = raw.get("url") or raw.get("playlist_url") or raw.get("spotify_url") or raw.get("external_url") or ""
    if not url and (external_id or playlist_id):
        url = f"https://open.spotify.com/playlist/{external_id or playlist_id}"
    owner = raw.get("curator") or raw.get("curator_name") or raw.get("owner_name") or raw.get("owner") or raw.get("user_name") or ""
    followers = raw.get("followers") or raw.get("follower_count") or raw.get("spotify_followers") or 0
    description = raw.get("description") or raw.get("spotify_description") or ""
    source_artist = raw.get("source_artist_name") or ""
    if source_artist and source_artist not in description:
        description = f"{description} {source_artist}".strip()
    updated = raw.get("last_updated") or raw.get("modified_at") or raw.get("updated_at") or raw.get("last_track_added_at") or ""
    return {
        "source_playlist_id": str(playlist_id),
        "playlist_name": name,
        "playlist_url": url,
        "curator_name": owner,
        "follower_count": followers,
        "spotify_description": description,
        "last_updated": updated,
        "source": "viberate",
        "search_query": query,
        "raw": raw,
    }


def extract_playlist_items(response: Dict) -> List[Dict]:
    if not isinstance(response, dict):
        return []
    for key in ["playlists", "data", "results", "items", "obj"]:
        value = response.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            for nested in ["playlists", "data", "results", "items"]:
                if isinstance(value.get(nested), list):
                    return value[nested]
    return []


def viberate_status() -> Dict[str, str]:
    client = ViberateAPI()
    return {
        "configured": "yes" if client.configured else "no",
        "base_url": client.base_url,
    }
