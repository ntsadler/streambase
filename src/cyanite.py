import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, Optional

import requests

from src.settings import load_local_env


load_local_env()


CYANITE_API_URL = os.getenv("CYANITE_API_URL", "https://api.cyanite.ai/graphql")


class CyaniteAPIError(RuntimeError):
    pass


def ffmpeg_executable() -> str:
    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        return system_ffmpeg
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return ""


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
        try:
            payload = resp.json()
        except ValueError:
            payload = {}
        if resp.status_code >= 400:
            message = "; ".join([err.get("message", "") for err in payload.get("errors", []) if err.get("message")])
            raise CyaniteAPIError(message or f"Cyanite API returned HTTP {resp.status_code}.")
        if payload.get("errors"):
            message = "; ".join([err.get("message", "") for err in payload.get("errors", []) if err.get("message")])
            raise CyaniteAPIError(message or "Cyanite returned a GraphQL error.")
        return payload

    def status(self) -> Dict:
        if not self.configured:
            return {"configured": "no", "message": "Set CYANITE_API_KEY to enable deep audio analysis."}
        return {"configured": "yes", "message": "Cyanite API key is configured."}

    def request_file_upload(self) -> Dict:
        query = """
        mutation StreambaseFileUploadRequest {
          fileUploadRequest {
            id
            uploadUrl
          }
        }
        """
        return self.graphql(query)

    def create_library_track(self, upload_id: str, title: str = "", external_id: str = "") -> Dict:
        query = """
        mutation StreambaseLibraryTrackCreate($input: LibraryTrackCreateInput!) {
          libraryTrackCreate(input: $input) {
            __typename
            ... on LibraryTrackCreateSuccess {
              createdLibraryTrack {
                id
                title
              }
            }
            ... on LibraryTrackCreateError {
              code
              message
            }
          }
        }
        """
        payload = {"uploadId": upload_id}
        if title:
            payload["title"] = title
        if external_id:
            payload["externalId"] = external_id
        return self.graphql(query, {"input": payload})

    def upload_mp3_and_create_track(self, audio_bytes: bytes, title: str = "", external_id: str = "") -> Dict:
        upload = self.request_file_upload()
        request = ((upload.get("data") or {}).get("fileUploadRequest") or {})
        upload_id = request.get("id", "")
        upload_url = request.get("uploadUrl", "")
        if not upload_id or not upload_url:
            return {"ok": False, "error": request.get("message") or "Cyanite did not return an upload URL.", "raw": upload}
        put = requests.put(upload_url, data=audio_bytes, headers={"Content-Type": "audio/mpeg"}, timeout=self.timeout)
        put.raise_for_status()
        created = self.create_library_track(upload_id, title, external_id)
        result = ((created.get("data") or {}).get("libraryTrackCreate") or {})
        if result.get("__typename") == "LibraryTrackCreateSuccess":
            track = result.get("createdLibraryTrack") or {}
            return {"ok": True, "library_track_id": track.get("id", ""), "title": track.get("title", title), "raw": created}
        return {"ok": False, "error": result.get("message") or "Cyanite library track creation failed.", "raw": created}

    def get_library_track_analysis(self, library_track_id: str) -> Dict:
        query = """
        query StreambaseLibraryTrackAnalysis($trackId: ID!) {
          libraryTrack(id: $trackId) {
            __typename
            ... on Error {
              message
            }
            ... on LibraryTrack {
              id
              title
              audioAnalysisV7 {
                __typename
                ... on AudioAnalysisV7Finished {
                  result {
                    advancedGenreTags
                    advancedSubgenreTags
                    advancedInstrumentTags
                    advancedInstrumentTagsExtended
                    moodTags
                    moodAdvancedTags
                    instrumentTags
                    voiceTags
                    movementTags
                    characterTags
                    freeGenreTags
                    bpmRangeAdjusted
                    musicalEraTag
                    timeSignature
                    transformerCaption
                    valence
                    arousal
                  }
                }
                ... on AudioAnalysisV7Failed {
                  error {
                    message
                  }
                }
              }
            }
          }
        }
        """
        return self.graphql(query, {"trackId": library_track_id})


def cyanite_label(value) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    out = []
    for i, ch in enumerate(text):
        if i and ch.isupper() and text[i - 1].islower():
            out.append(" ")
        out.append(ch)
    return "".join(out).replace("_", " ").replace("-", " ").lower()


def normalize_cyanite_analysis(raw: Dict) -> Dict:
    track = ((raw.get("data") or {}).get("libraryTrack") or {})
    if not track:
        return {"ok": False, "status": "not_found", "error": "No Cyanite library track found.", "raw": raw}
    if track.get("__typename") != "LibraryTrack":
        return {"ok": False, "status": "error", "error": track.get("message") or "Cyanite returned an error.", "raw": raw}
    analysis = track.get("audioAnalysisV7") or {}
    typename = analysis.get("__typename", "")
    if typename != "AudioAnalysisV7Finished":
        return {
            "ok": False,
            "status": typename.replace("AudioAnalysisV7", "").lower() or "processing",
            "error": analysis.get("message") or (analysis.get("error") or {}).get("message") or "Cyanite analysis is not finished yet.",
            "library_track_id": track.get("id", ""),
            "title": track.get("title", ""),
            "raw": raw,
        }
    result = analysis.get("result") or {}
    genre_tags = [cyanite_label(x) for x in (result.get("advancedGenreTags") or result.get("genreTags") or []) if x]
    subgenre_tags = [cyanite_label(x) for x in (result.get("advancedSubgenreTags") or []) if x]
    mood_tags = [cyanite_label(x) for x in (result.get("moodAdvancedTags") or result.get("moodTags") or []) if x]
    instrument_tags = [cyanite_label(x) for x in (result.get("advancedInstrumentTagsExtended") or result.get("advancedInstrumentTags") or result.get("instrumentTags") or []) if x]
    voice_tags = [cyanite_label(x) for x in (result.get("voiceTags") or []) if x]
    movement_tags = [cyanite_label(x) for x in (result.get("movementTags") or []) if x]
    character_tags = [cyanite_label(x) for x in (result.get("characterTags") or []) if x]
    descriptors = genre_tags + subgenre_tags + mood_tags + instrument_tags + movement_tags + character_tags
    arousal = result.get("arousal")
    energy = "high" if isinstance(arousal, (int, float)) and arousal >= 0.66 else "medium" if isinstance(arousal, (int, float)) and arousal >= 0.33 else "low" if isinstance(arousal, (int, float)) else ""
    return {
        "ok": True,
        "status": "finished",
        "source": "cyanite_audio_analysis_v7",
        "library_track_id": track.get("id", ""),
        "title": track.get("title", ""),
        "genres": list(dict.fromkeys(genre_tags + subgenre_tags)),
        "moods": list(dict.fromkeys(mood_tags + character_tags)),
        "instruments": list(dict.fromkeys(instrument_tags)),
        "voice": "; ".join(voice_tags),
        "movement": "; ".join(movement_tags),
        "energy": energy,
        "bpm": result.get("bpmRangeAdjusted", ""),
        "valence": result.get("valence", ""),
        "arousal": arousal if arousal is not None else "",
        "time_signature": result.get("timeSignature", ""),
        "musical_era": result.get("musicalEraTag", ""),
        "caption": result.get("transformerCaption", ""),
        "descriptors": "; ".join([x for x in descriptors if x]),
        "raw": raw,
    }


def fetch_cyanite_analysis(library_track_id: str) -> Dict:
    client = CyaniteAPI()
    if not client.configured:
        return {"ok": False, "status": "not_configured", "error": "Set CYANITE_API_KEY before fetching Cyanite analysis."}
    if not library_track_id:
        return {"ok": False, "status": "missing_id", "error": "Missing Cyanite library track ID."}
    try:
        return normalize_cyanite_analysis(client.get_library_track_analysis(library_track_id))
    except (requests.RequestException, CyaniteAPIError) as exc:
        return {"ok": False, "status": "request_failed", "error": str(exc)}


def prepare_audio_for_cyanite(uploaded_file) -> Dict:
    if not uploaded_file:
        return {"ok": False, "error": "Upload a WAV or MP3 file first."}
    name = getattr(uploaded_file, "name", "") or "song"
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    data = uploaded_file.getvalue()
    if ext == "mp3":
        return {"ok": True, "audio_bytes": data, "file_name": name, "format": "mp3", "converted": False}
    if ext != "wav":
        return {"ok": False, "error": "Cyanite API uploads expect MP3. Upload MP3, or upload WAV so Streambase can convert it."}
    ffmpeg = ffmpeg_executable()
    if not ffmpeg:
        return {"ok": False, "error": "WAV upload needs ffmpeg. Install imageio-ffmpeg with `python3 -m pip install imageio-ffmpeg`, or install system ffmpeg."}
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "streambase-input.wav"
        dst = Path(tmp) / "streambase-cyanite.mp3"
        src.write_bytes(data)
        cmd = [ffmpeg, "-y", "-i", str(src), "-codec:a", "libmp3lame", "-b:a", "192k", str(dst)]
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if proc.returncode != 0 or not dst.exists():
            detail = (proc.stderr or proc.stdout or "").strip().splitlines()[-1:] or ["Unknown ffmpeg error."]
            return {"ok": False, "error": "Could not convert WAV to MP3: " + detail[0]}
        return {"ok": True, "audio_bytes": dst.read_bytes(), "file_name": name.rsplit(".", 1)[0] + ".mp3", "format": "mp3", "converted": True}


def upload_song_audio_to_cyanite(uploaded_file, title: str = "", external_id: str = "") -> Dict:
    prepared = prepare_audio_for_cyanite(uploaded_file)
    if not prepared.get("ok"):
        return prepared
    client = CyaniteAPI()
    if not client.configured:
        return {
            "ok": False,
            "prepared": True,
            "file_name": prepared.get("file_name", ""),
            "converted": prepared.get("converted", False),
            "error": "Set CYANITE_API_KEY before sending audio to Cyanite.",
        }
    try:
        result = client.upload_mp3_and_create_track(prepared["audio_bytes"], title, external_id)
    except (requests.RequestException, CyaniteAPIError) as exc:
        result = {"ok": False, "error": str(exc) or "Cyanite upload failed."}
    return {**result, "prepared": True, "file_name": prepared.get("file_name", ""), "converted": prepared.get("converted", False)}


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
