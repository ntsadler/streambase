"""Read-only access to the Streambase song catalog.

This module intentionally does not import ``src.database``.  The catalog API
must never initialize, migrate, or write to the main Streambase database.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import stat
from contextlib import closing
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = ROOT_DIR / "local_data" / "streambase.sqlite"
DEFAULT_AUDIO_ROOT = ROOT_DIR / "data" / "audio_uploads"
SUPPORTED_AUDIO_SUFFIXES = {".mp3", ".wav"}
NUMERIC_NOISE_TAG = re.compile(r"^\d{1,3}$")


class CatalogUnavailable(RuntimeError):
    """Raised when the configured catalog cannot be read safely."""


class TrackNotFound(LookupError):
    """Raised when a requested song ID is absent."""


class AudioUnavailable(LookupError):
    """Raised when a song has no safely resolvable audio file."""


def _configured_path(value: str | os.PathLike[str] | None, default: Path) -> Path:
    raw = Path(value).expanduser() if value else default
    if not raw.is_absolute():
        raw = ROOT_DIR / raw
    return raw.resolve(strict=False)


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).replace("\x00", "").strip()
    return text or None


def _number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _tag_values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        values: list[str] = []
        for item in value:
            values.extend(_tag_values(item))
        return values
    text = str(value).replace("\x00", "").strip()
    if not text:
        return []
    return [part.strip() for part in text.split(";") if part.strip()]


def _clean_tags(*values: Any) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for value in values:
        for tag in _tag_values(value):
            if NUMERIC_NOISE_TAG.fullmatch(tag):
                continue
            key = tag.casefold()
            if key in seen:
                continue
            seen.add(key)
            cleaned.append(tag)
    return cleaned


def _parse_raw_analysis(value: Any) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class CatalogRepository:
    """Small repository with a new read-only SQLite connection per operation."""

    def __init__(
        self,
        db_path: str | os.PathLike[str] | None = None,
        audio_root: str | os.PathLike[str] | None = None,
    ) -> None:
        self.db_path = _configured_path(
            db_path or os.getenv("STREAMBASE_CATALOG_DB_PATH"),
            DEFAULT_DB_PATH,
        )
        self.audio_root = _configured_path(
            audio_root or os.getenv("STREAMBASE_CATALOG_AUDIO_ROOT"),
            DEFAULT_AUDIO_ROOT,
        )

    def _connect(self) -> sqlite3.Connection:
        if not self.db_path.is_file():
            raise CatalogUnavailable("Catalog database is unavailable.")
        try:
            connection = sqlite3.connect(
                f"{self.db_path.as_uri()}?mode=ro",
                uri=True,
                timeout=3,
            )
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA query_only=ON")
            connection.execute("PRAGMA busy_timeout=3000")
            return connection
        except sqlite3.Error as exc:
            raise CatalogUnavailable("Catalog database is unavailable.") from exc

    def list_tracks(
        self,
        *,
        search: str = "",
        mood: str = "",
        energy: str = "",
        limit: int = 25,
        last_id: int = 0,
    ) -> tuple[list[dict[str, Any]], int, bool]:
        normalized_search = search.strip()
        clauses = ["s.id > ?"]
        page_args: list[Any] = [max(0, int(last_id))]
        count_clauses: list[str] = []
        count_args: list[Any] = []
        if normalized_search:
            pattern = f"%{_escape_like(normalized_search.casefold())}%"
            search_clause = "(LOWER(COALESCE(s.title,'')) LIKE ? ESCAPE '\\' OR LOWER(COALESCE(s.artist_name,'')) LIKE ? ESCAPE '\\')"
            clauses.append(search_clause)
            count_clauses.append(search_clause)
            page_args.extend([pattern, pattern])
            count_args.extend([pattern, pattern])
        normalized_mood = mood.strip().casefold().replace(" ", "")
        if normalized_mood:
            mood_clause = "(';' || LOWER(REPLACE(COALESCE(p.mood_tags,''),' ','')) || ';') LIKE ? ESCAPE '\\'"
            mood_pattern = f"%;{_escape_like(normalized_mood)};%"
            clauses.append(mood_clause)
            count_clauses.append(mood_clause)
            page_args.append(mood_pattern)
            count_args.append(mood_pattern)
        normalized_energy = energy.strip().casefold()
        if normalized_energy:
            energy_clause = "LOWER(TRIM(COALESCE(p.energy,''))) = ?"
            clauses.append(energy_clause)
            count_clauses.append(energy_clause)
            page_args.append(normalized_energy)
            count_args.append(normalized_energy)

        where = " WHERE " + " AND ".join(clauses)
        count_where = " WHERE " + " AND ".join(count_clauses) if count_clauses else ""
        page_args.append(int(limit) + 1)
        select_sql = self._select_sql() + where + " ORDER BY s.id ASC LIMIT ?"
        count_sql = "SELECT COUNT(*) " + self._from_sql() + count_where

        try:
            with closing(self._connect()) as connection:
                rows = connection.execute(select_sql, page_args).fetchall()
                total = int(connection.execute(count_sql, count_args).fetchone()[0])
        except CatalogUnavailable:
            raise
        except sqlite3.Error as exc:
            raise CatalogUnavailable("Catalog database is unavailable.") from exc

        has_more = len(rows) > limit
        return [self._serialize_track(row) for row in rows[:limit]], total, has_more

    def get_track(self, song_id: int) -> dict[str, Any]:
        try:
            with closing(self._connect()) as connection:
                row = connection.execute(
                    self._select_sql() + " WHERE s.id=?",
                    (int(song_id),),
                ).fetchone()
        except CatalogUnavailable:
            raise
        except sqlite3.Error as exc:
            raise CatalogUnavailable("Catalog database is unavailable.") from exc
        if row is None:
            raise TrackNotFound("Track not found.")
        return self._serialize_track(row)

    def get_audio_path(self, song_id: int) -> Path:
        try:
            with closing(self._connect()) as connection:
                row = connection.execute(
                    "SELECT file_name FROM songs WHERE id=?",
                    (int(song_id),),
                ).fetchone()
        except CatalogUnavailable:
            raise
        except sqlite3.Error as exc:
            raise CatalogUnavailable("Catalog database is unavailable.") from exc
        if row is None:
            raise TrackNotFound("Track not found.")
        return self._resolve_audio_name(row["file_name"])

    @staticmethod
    def _select_sql() -> str:
        return """SELECT s.id,s.title,s.file_name,s.release_status,s.planned_release_date,s.artist_name,
                         p.bpm,p.key,p.genre_tags,p.mood_tags,p.energy,p.danceability,
                         p.instrumentation,p.vocal_style,p.analysis_source,p.source,p.raw_analysis_json
                  """ + CatalogRepository._from_sql()

    @staticmethod
    def _from_sql() -> str:
        return """FROM songs s
                  LEFT JOIN song_audio_profiles p ON p.song_id=s.id"""

    def _resolve_audio_name(self, value: Any) -> Path:
        file_name = value if isinstance(value, str) else ""
        if (
            not file_name
            or "\x00" in file_name
            or "/" in file_name
            or "\\" in file_name
            or Path(file_name).name != file_name
            or Path(file_name).suffix.lower() not in SUPPORTED_AUDIO_SUFFIXES
        ):
            raise AudioUnavailable("Audio is unavailable.")
        try:
            root = self.audio_root.resolve(strict=True)
            if not root.is_dir():
                raise AudioUnavailable("Audio is unavailable.")
            candidate = root / file_name
            file_stat = candidate.lstat()
            if stat.S_ISLNK(file_stat.st_mode) or not stat.S_ISREG(file_stat.st_mode):
                raise AudioUnavailable("Audio is unavailable.")
            resolved = candidate.resolve(strict=True)
            if not resolved.is_relative_to(root):
                raise AudioUnavailable("Audio is unavailable.")
            return resolved
        except AudioUnavailable:
            raise
        except (FileNotFoundError, OSError, RuntimeError) as exc:
            raise AudioUnavailable("Audio is unavailable.") from exc

    def _serialize_track(self, row: sqlite3.Row) -> dict[str, Any]:
        raw = _parse_raw_analysis(row["raw_analysis_json"])
        try:
            self._resolve_audio_name(row["file_name"])
            audio_available = True
        except AudioUnavailable:
            audio_available = False
        song_id = int(row["id"])
        return {
            "id": song_id,
            "ref": f"streambase:song:{song_id}",
            "title": _optional_text(row["title"]) or "Untitled",
            "artistName": _optional_text(row["artist_name"]) or "",
            "releaseStatus": _optional_text(row["release_status"]) or "unreleased",
            "plannedReleaseDate": _optional_text(row["planned_release_date"]),
            "audioAvailable": audio_available,
            "analysis": {
                "bpm": _number(row["bpm"]),
                "key": _optional_text(row["key"]),
                "energy": _optional_text(row["energy"]),
                "danceability": _number(row["danceability"]),
                "genres": _clean_tags(row["genre_tags"]),
                "moods": _clean_tags(row["mood_tags"]),
                "instruments": _clean_tags(row["instrumentation"]),
                "vocalStyle": _optional_text(row["vocal_style"]),
                "emotionalProfile": _optional_text(raw.get("emotional_profile")),
                "keywords": _clean_tags(raw.get("keywords")),
                "source": _optional_text(row["source"] or row["analysis_source"]),
            },
        }
