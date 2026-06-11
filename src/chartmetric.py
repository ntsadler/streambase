import os
from typing import Dict, Optional

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
        resp.raise_for_status()
        return resp.json()

    def search_artist(self, artist_name: str) -> Dict:
        return self.get("search", {"q": artist_name, "type": "artists"})

    def get_playlist_snapshot(self, playlist_id: str) -> Dict:
        return self.get(f"playlist/{playlist_id}")


def chartmetric_status() -> Dict[str, str]:
    client = ChartmetricAPI()
    return {
        "configured": "yes" if client.configured else "no",
        "base_url": client.base_url,
    }
