import os
from typing import Dict, List, Optional

import requests


class ChartmetricAPI:
    def __init__(
        self,
        api_token: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: int = 12,
    ):
        self.api_token = api_token or os.getenv("CHARTMETRIC_API_TOKEN", "")
        self.base_url = (base_url or os.getenv("CHARTMETRIC_API_BASE_URL", "https://api.chartmetric.com/api")).rstrip("/")
        self.timeout = timeout
        self.last_status_code = 0
        self.last_response_headers = {}

    @property
    def configured(self) -> bool:
        return bool(self.api_token)

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.api_token}", "Accept": "application/json"}

    def get(self, path: str, params: Optional[Dict] = None) -> Dict:
        if not self.configured:
            raise RuntimeError("Chartmetric API token is not configured.")
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

    def search_artist(self, artist_name: str) -> Dict:
        return self.get("search", {"q": artist_name, "type": "artists"})

    def search_playlists(self, query: str, limit: int = 25, offset: int = 0) -> Dict:
        return self.get("search", {"q": query, "type": "playlists", "limit": limit, "offset": offset})

    def search_playlists_by_artist(self, artist_name: str, limit: int = 25) -> Dict:
        return self.search_playlists(f"playlists containing {artist_name}", limit)

    def get_playlist_snapshot(self, playlist_id: str) -> Dict:
        return self.get(f"playlist/{playlist_id}")

    def get_playlist_tracks(self, playlist_id: str, limit: int = 100) -> Dict:
        return self.get(f"playlist/{playlist_id}/tracks", {"limit": limit})


def normalize_chartmetric_playlist(raw: Dict, query: str = "") -> Dict:
    raw = raw or {}
    playlist_id = raw.get("id") or raw.get("playlist_id") or raw.get("cm_playlist") or raw.get("cm_playlist_id") or ""
    name = raw.get("name") or raw.get("playlist_name") or raw.get("title") or ""
    url = raw.get("url") or raw.get("playlist_url") or raw.get("spotify_url") or raw.get("external_url") or ""
    owner = raw.get("curator_name") or raw.get("owner_name") or raw.get("owner") or raw.get("user_name") or ""
    followers = raw.get("followers") or raw.get("follower_count") or raw.get("spotify_followers") or 0
    description = raw.get("description") or raw.get("spotify_description") or ""
    updated = raw.get("last_updated") or raw.get("modified_at") or raw.get("updated_at") or raw.get("last_track_added_at") or ""
    return {
        "chartmetric_playlist_id": str(playlist_id),
        "playlist_name": name,
        "playlist_url": url,
        "curator_name": owner,
        "follower_count": followers,
        "spotify_description": description,
        "last_updated": updated,
        "source": "chartmetric",
        "search_query": query,
        "raw": raw,
    }


def extract_playlist_items(response: Dict) -> List[Dict]:
    if not isinstance(response, dict):
        return []
    for key in ["playlists", "data", "results", "obj"]:
        value = response.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            for nested in ["playlists", "data", "results"]:
                if isinstance(value.get(nested), list):
                    return value[nested]
    return []


def chartmetric_status() -> Dict[str, str]:
    client = ChartmetricAPI()
    return {
        "configured": "yes" if client.configured else "no",
        "base_url": client.base_url,
    }
