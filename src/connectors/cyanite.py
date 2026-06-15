from typing import Dict

from src.cyanite import CyaniteAPI, fetch_cyanite_analysis, upload_song_audio_to_cyanite


class CyaniteConnector:
    """Optional Cyanite connector facade used by catalog workflows."""

    def __init__(self):
        self.client = CyaniteAPI()

    @property
    def configured(self) -> bool:
        return self.client.configured

    def status(self) -> Dict:
        if not self.configured:
            return {"configured": "no", "message": "Cyanite not connected yet."}
        return {"configured": "yes", "message": "Cyanite connected."}

    def analyze_upload(self, uploaded_file, title: str = "", external_id: str = "") -> Dict:
        if not self.configured:
            return {"ok": False, "source": "manual", "error": "Cyanite not connected yet."}
        return upload_song_audio_to_cyanite(uploaded_file, title, external_id)

    def fetch_analysis(self, library_track_id: str) -> Dict:
        if not self.configured:
            return {"ok": False, "source": "manual", "error": "Cyanite not connected yet."}
        return fetch_cyanite_analysis(library_track_id)
