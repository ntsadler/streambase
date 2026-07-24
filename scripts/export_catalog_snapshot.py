#!/usr/bin/env python3
"""Build a private, catalog-only Streambase snapshot for deployment.

The exporter deliberately reads a small allowlist of columns instead of
copying the CRM database. It also copies only the MP3/WAV files referenced by
the exported songs. The destination must not already exist, so a failed or
mistyped export cannot overwrite an earlier bundle.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import stat
import tempfile
import unicodedata
from contextlib import closing
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable


ROOT_DIR = Path(__file__).resolve().parents[1]
DEPLOY_FILES = {
    ROOT_DIR / "deploy" / "catalog" / "Dockerfile": Path("Dockerfile"),
    ROOT_DIR / "deploy" / "catalog" / "requirements.txt": Path("requirements.txt"),
    ROOT_DIR / "src" / "__init__.py": Path("src/__init__.py"),
    ROOT_DIR / "src" / "catalog_api.py": Path("src/catalog_api.py"),
    ROOT_DIR / "src" / "catalog_repository.py": Path("src/catalog_repository.py"),
}
SUPPORTED_AUDIO_SUFFIXES = {".mp3", ".wav"}
SONG_COLUMNS = (
    "id",
    "title",
    "file_name",
    "release_status",
    "planned_release_date",
    "artist_name",
)
PROFILE_COLUMNS = (
    "song_id",
    "bpm",
    "key",
    "genre_tags",
    "mood_tags",
    "energy",
    "danceability",
    "instrumentation",
    "vocal_style",
    "analysis_source",
    "source",
    "raw_analysis_json",
)


class CatalogSnapshotError(RuntimeError):
    """Raised when a safe deployment snapshot cannot be produced."""


@dataclass(frozen=True)
class ExportResult:
    output_dir: str
    track_count: int
    profile_count: int
    audio_file_count: int
    cloud_run_context: bool


def _open_read_only_database(path: Path) -> sqlite3.Connection:
    try:
        connection = sqlite3.connect(
            f"{path.as_uri()}?mode=ro",
            uri=True,
            timeout=10,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        connection.execute("PRAGMA busy_timeout=10000")
        return connection
    except sqlite3.Error as exc:
        raise CatalogSnapshotError("The source catalog database could not be opened read-only.") from exc


def _resolved_file(path: str | os.PathLike[str], label: str) -> Path:
    try:
        resolved = Path(path).expanduser().resolve(strict=True)
    except (FileNotFoundError, OSError, RuntimeError) as exc:
        raise CatalogSnapshotError(f"{label} does not exist.") from exc
    if not resolved.is_file():
        raise CatalogSnapshotError(f"{label} must be a regular file.")
    return resolved


def _resolved_directory(path: str | os.PathLike[str], label: str) -> Path:
    try:
        resolved = Path(path).expanduser().resolve(strict=True)
    except (FileNotFoundError, OSError, RuntimeError) as exc:
        raise CatalogSnapshotError(f"{label} does not exist.") from exc
    if not resolved.is_dir():
        raise CatalogSnapshotError(f"{label} must be a directory.")
    return resolved


def _validated_audio_name(value: Any) -> str:
    if not isinstance(value, str):
        raise CatalogSnapshotError("Every exported song must have a safe audio filename.")
    file_name = value
    path_name = Path(file_name)
    if (
        not file_name
        or file_name != file_name.strip()
        or any(ord(character) < 32 for character in file_name)
        or "/" in file_name
        or "\\" in file_name
        or path_name.name != file_name
        or not path_name.stem
        or path_name.suffix.casefold() not in SUPPORTED_AUDIO_SUFFIXES
    ):
        raise CatalogSnapshotError(f"Unsafe audio filename: {file_name!r}.")
    return file_name


def _safe_audio_path(audio_root: Path, file_name: str) -> Path:
    candidate = audio_root / file_name
    try:
        file_stat = candidate.lstat()
        if stat.S_ISLNK(file_stat.st_mode) or not stat.S_ISREG(file_stat.st_mode):
            raise CatalogSnapshotError(f"Audio must be a regular, non-symlink file: {file_name!r}.")
        resolved = candidate.resolve(strict=True)
    except CatalogSnapshotError:
        raise
    except (FileNotFoundError, OSError, RuntimeError) as exc:
        raise CatalogSnapshotError(f"Referenced audio is missing: {file_name!r}.") from exc
    if not resolved.is_relative_to(audio_root):
        raise CatalogSnapshotError(f"Audio escapes the configured root: {file_name!r}.")
    return resolved


def _sanitize_raw_analysis(value: Any) -> str:
    try:
        parsed = json.loads(str(value)) if value else {}
    except (TypeError, ValueError, json.JSONDecodeError):
        parsed = {}
    if not isinstance(parsed, dict):
        parsed = {}

    safe: dict[str, Any] = {}
    emotional_profile = parsed.get("emotional_profile")
    if isinstance(emotional_profile, (str, int, float)) and not isinstance(emotional_profile, bool):
        text = str(emotional_profile).replace("\x00", "").strip()
        if text:
            safe["emotional_profile"] = text

    keywords = parsed.get("keywords")
    if isinstance(keywords, str):
        text = keywords.replace("\x00", "").strip()
        if text:
            safe["keywords"] = text
    elif isinstance(keywords, (list, tuple)):
        cleaned_keywords = []
        for keyword in keywords:
            if not isinstance(keyword, (str, int, float)) or isinstance(keyword, bool):
                continue
            text = str(keyword).replace("\x00", "").strip()
            if text:
                cleaned_keywords.append(text)
        if cleaned_keywords:
            safe["keywords"] = cleaned_keywords

    return json.dumps(safe, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _copy_regular_file(source: Path, destination: Path) -> None:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        source_fd = os.open(source, flags)
    except OSError as exc:
        raise CatalogSnapshotError(f"Audio could not be opened safely: {source.name!r}.") from exc
    try:
        source_stat = os.fstat(source_fd)
        if not stat.S_ISREG(source_stat.st_mode):
            raise CatalogSnapshotError(f"Audio is not a regular file: {source.name!r}.")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with os.fdopen(source_fd, "rb", closefd=False) as source_file:
            with destination.open("xb") as destination_file:
                shutil.copyfileobj(source_file, destination_file, length=1024 * 1024)
        destination.chmod(0o600)
    except OSError as exc:
        raise CatalogSnapshotError(f"Audio could not be copied: {source.name!r}.") from exc
    finally:
        os.close(source_fd)


def _load_allowlisted_rows(
    connection: sqlite3.Connection,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    try:
        songs = [
            dict(row)
            for row in connection.execute(
                f"SELECT {','.join(SONG_COLUMNS)} FROM songs ORDER BY id ASC"
            ).fetchall()
        ]
        profiles = [
            dict(row)
            for row in connection.execute(
                f"""SELECT {','.join(f'p.{column}' for column in PROFILE_COLUMNS)}
                    FROM song_audio_profiles p
                    INNER JOIN songs s ON s.id=p.song_id
                    ORDER BY p.song_id ASC"""
            ).fetchall()
        ]
    except sqlite3.Error as exc:
        raise CatalogSnapshotError("The source database is missing required catalog columns.") from exc
    if not songs:
        raise CatalogSnapshotError("The source catalog contains no songs.")
    return songs, profiles


def _write_minimal_database(
    destination: Path,
    songs: list[dict[str, Any]],
    profiles: list[dict[str, Any]],
) -> None:
    try:
        with closing(sqlite3.connect(destination)) as connection:
            connection.execute("PRAGMA foreign_keys=ON")
            connection.executescript(
                """
                CREATE TABLE songs (
                    id INTEGER PRIMARY KEY,
                    title TEXT,
                    file_name TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    release_status TEXT,
                    planned_release_date TEXT,
                    artist_name TEXT
                );
                CREATE TABLE song_audio_profiles (
                    song_id INTEGER PRIMARY KEY REFERENCES songs(id) ON DELETE CASCADE,
                    bpm REAL,
                    key TEXT,
                    genre_tags TEXT,
                    mood_tags TEXT,
                    energy TEXT,
                    danceability REAL,
                    instrumentation TEXT,
                    vocal_style TEXT,
                    analysis_source TEXT,
                    source TEXT,
                    raw_analysis_json TEXT
                );
                PRAGMA user_version=1;
                """
            )
            connection.executemany(
                f"INSERT INTO songs ({','.join(SONG_COLUMNS)}) VALUES ({','.join('?' for _ in SONG_COLUMNS)})",
                [tuple(song[column] for column in SONG_COLUMNS) for song in songs],
            )
            profile_values = []
            for profile in profiles:
                profile = dict(profile)
                profile["raw_analysis_json"] = _sanitize_raw_analysis(profile["raw_analysis_json"])
                profile_values.append(tuple(profile[column] for column in PROFILE_COLUMNS))
            connection.executemany(
                f"""INSERT INTO song_audio_profiles ({','.join(PROFILE_COLUMNS)})
                    VALUES ({','.join('?' for _ in PROFILE_COLUMNS)})""",
                profile_values,
            )
            connection.commit()
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                raise CatalogSnapshotError("The exported catalog failed its SQLite integrity check.")
            connection.execute("VACUUM")
    except CatalogSnapshotError:
        raise
    except sqlite3.Error as exc:
        raise CatalogSnapshotError("The minimal catalog database could not be created.") from exc
    destination.chmod(0o600)


def _populate_snapshot(
    source_db: Path,
    audio_root: Path,
    destination: Path,
) -> tuple[int, int, int]:
    destination.mkdir(parents=True, exist_ok=True)
    if any(destination.iterdir()):
        raise CatalogSnapshotError("The snapshot staging directory must be empty.")
    with closing(_open_read_only_database(source_db)) as connection:
        connection.execute("BEGIN")
        songs, profiles = _load_allowlisted_rows(connection)

        audio_names: list[str] = []
        seen_names: set[str] = set()
        for song in songs:
            song_id = song["id"]
            if isinstance(song_id, bool) or not isinstance(song_id, int) or song_id <= 0:
                raise CatalogSnapshotError("Every exported song must have a positive integer ID.")
            file_name = _validated_audio_name(song["file_name"])
            normalized_name = unicodedata.normalize("NFC", file_name).casefold()
            if normalized_name in seen_names:
                raise CatalogSnapshotError(f"Duplicate audio filename: {file_name!r}.")
            seen_names.add(normalized_name)
            audio_names.append(file_name)
        audio_sources = []
        for song, source_name in zip(songs, audio_names, strict=True):
            source_audio = _safe_audio_path(audio_root, source_name)
            exported_name = f"song-{song['id']}{Path(source_name).suffix.casefold()}"
            song["file_name"] = exported_name
            audio_sources.append((exported_name, source_audio))

        _write_minimal_database(destination / "catalog.sqlite", songs, profiles)
        audio_destination = destination / "audio"
        audio_destination.mkdir()
        audio_destination.chmod(0o700)
        for file_name, source_audio in audio_sources:
            _copy_regular_file(source_audio, audio_destination / file_name)

    destination.chmod(0o700)
    return len(songs), len(profiles), len(audio_sources)


def _atomic_directory(
    destination: str | os.PathLike[str],
    builder: Callable[[Path], tuple[int, int, int]],
) -> tuple[Path, tuple[int, int, int]]:
    destination_path = Path(destination).expanduser().resolve(strict=False)
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    if os.path.lexists(destination_path):
        raise CatalogSnapshotError("The output directory already exists; choose a new empty destination.")

    staging_path = Path(
        tempfile.mkdtemp(
            prefix=f".{destination_path.name}-",
            dir=destination_path.parent,
        )
    )
    try:
        counts = builder(staging_path)
        os.replace(staging_path, destination_path)
    except Exception:
        shutil.rmtree(staging_path, ignore_errors=True)
        raise
    return destination_path, counts


def export_catalog_snapshot(
    source_db: str | os.PathLike[str],
    audio_root: str | os.PathLike[str],
    output_dir: str | os.PathLike[str],
) -> ExportResult:
    source_db_path = _resolved_file(source_db, "Source database")
    audio_root_path = _resolved_directory(audio_root, "Audio root")
    destination, counts = _atomic_directory(
        output_dir,
        lambda staging: _populate_snapshot(source_db_path, audio_root_path, staging),
    )
    return ExportResult(
        output_dir=str(destination),
        track_count=counts[0],
        profile_count=counts[1],
        audio_file_count=counts[2],
        cloud_run_context=False,
    )


def prepare_cloud_run_context(
    source_db: str | os.PathLike[str],
    audio_root: str | os.PathLike[str],
    output_dir: str | os.PathLike[str],
) -> ExportResult:
    source_db_path = _resolved_file(source_db, "Source database")
    audio_root_path = _resolved_directory(audio_root, "Audio root")

    def build_context(staging: Path) -> tuple[int, int, int]:
        counts = _populate_snapshot(
            source_db_path,
            audio_root_path,
            staging / "catalog_data",
        )
        for source, relative_destination in DEPLOY_FILES.items():
            source_path = _resolved_file(source, f"Deployment source {source.name}")
            destination_path = staging / relative_destination
            destination_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source_path, destination_path)
            destination_path.chmod(0o600)
        return counts

    destination, counts = _atomic_directory(output_dir, build_context)
    return ExportResult(
        output_dir=str(destination),
        track_count=counts[0],
        profile_count=counts[1],
        audio_file_count=counts[2],
        cloud_run_context=True,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-db", required=True, help="Path to the private Streambase SQLite database.")
    parser.add_argument("--audio-root", required=True, help="Directory containing the source MP3/WAV files.")
    parser.add_argument("--output-dir", required=True, help="New destination directory; it must not already exist.")
    parser.add_argument(
        "--cloud-run-context",
        action="store_true",
        help="Produce a complete, minimal Cloud Run source-deploy context.",
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    try:
        if args.cloud_run_context:
            result = prepare_cloud_run_context(args.source_db, args.audio_root, args.output_dir)
        else:
            result = export_catalog_snapshot(args.source_db, args.audio_root, args.output_dir)
    except CatalogSnapshotError as exc:
        raise SystemExit(f"Catalog export failed: {exc}") from exc
    print(json.dumps(asdict(result), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
