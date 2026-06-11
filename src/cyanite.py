import os
from typing import Dict, Optional

import requests

from src.settings import load_local_env


load_local_env()


CYANITE_API_URL = os.getenv("CYANITE_API_URL", "https://api.cyanite.ai/graphql")


class CyaniteAPI:
    def __init__(self, api_key: Optional[str] = None, timeout: int = 30):
        self.api_key = api_key or os.getenv("CYANITE_API_KEY", "")
        self.timeout = timeout

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def _headers(self) -> Dict[str, str]:
        if not self.configured:
            raise RuntimeError("Cyanite API key is not configured.")
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def graphql(self, query: str, variables=None) -> Dict:
        resp = requests.post(
            CYANITE_API_URL,
            headers=self._headers(),
            json={"query": query, "variables": variables or {}},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()

    def status(self) -> Dict:
        if not self.configured:
            return {"configured": "no", "message": "Set CYANITE_API_KEY to enable deep audio analysis."}
        return {"configured": "yes", "message": "Cyanite API key is configured."}


def normalize_cyanite_tags(raw: Dict) -> Dict:
    if not raw:
        return {}

    def flatten(value):
        if isinstance(value, list):
            out = []
            for item in value:
                if isinstance(item, str):
                    out.append(item)
                elif isinstance(item, dict):
                    label = item.get("name") or item.get("label") or item.get("tag")
                    if label:
                        out.append(str(label))
            return out
        return []

    genres = flatten(raw.get("genres") or raw.get("genreTags"))
    moods = flatten(raw.get("moods") or raw.get("moodTags"))
    instruments = flatten(raw.get("instruments") or raw.get("instrumentTags"))
    keywords = flatten(raw.get("keywords") or raw.get("tags"))
    energy = raw.get("energy") or raw.get("energyLevel") or ""
    voice = raw.get("voice") or raw.get("vocalPresence") or ""
    bpm = raw.get("bpm") or raw.get("tempo") or ""

    return {
        "source": "cyanite",
        "genres": genres,
        "moods": moods,
        "instruments": instruments,
        "keywords": keywords,
        "energy": energy,
        "voice": voice,
        "bpm": bpm,
        "descriptors": "; ".join([str(x) for x in genres + moods + instruments + keywords if x]),
    }


def cyanite_status() -> Dict:
    return CyaniteAPI().status()
