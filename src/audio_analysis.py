from pathlib import Path
from typing import Dict

from src.settings import project_data_path
from src.song_analyzer import audio_summary


SUPPORTED_AUDIO_EXTENSIONS = {"wav", "mp3"}


def audio_upload_dir() -> Path:
    path = project_data_path("audio_uploads")
    path.mkdir(parents=True, exist_ok=True)
    return path


def clean_filename(name: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_", ".", " "} else "_" for ch in name or "song")
    return "_".join(safe.strip().split()) or "song"


def title_from_filename(name: str) -> str:
    stem = Path(name or "Untitled").stem.replace("_", " ").replace("-", " ").strip()
    return " ".join(stem.split()).title() or "Untitled"


def save_uploaded_song_file(uploaded_file) -> Dict:
    if not uploaded_file:
        return {"ok": False, "error": "Choose a WAV or MP3 file first."}
    name = clean_filename(getattr(uploaded_file, "name", "") or "song")
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext not in SUPPORTED_AUDIO_EXTENSIONS:
        return {"ok": False, "error": "Artist Sound Profile accepts WAV and MP3 files."}
    data = uploaded_file.getvalue()
    path = audio_upload_dir() / name
    path.write_bytes(data)
    summary = audio_summary(uploaded_file)
    return {
        "ok": True,
        "title": title_from_filename(name),
        "file_path": str(path),
        "file_name": name,
        "file_type": ext,
        "size_mb": summary.get("size_mb", round(len(data) / 1024 / 1024, 2)),
        "audio_summary": summary,
    }


def cyanite_ready_note(file_path: str) -> str:
    ext = Path(file_path or "").suffix.lower().strip(".")
    if ext == "mp3":
        return "Ready for Cyanite API upload."
    if ext == "wav":
        return "WAV stored locally; Streambase can convert it to MP3 before Cyanite upload."
    return "Add a WAV or MP3 file before Cyanite analysis."
