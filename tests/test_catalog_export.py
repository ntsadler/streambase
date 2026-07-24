import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from scripts.export_catalog_snapshot import (
    CatalogSnapshotError,
    export_catalog_snapshot,
    prepare_cloud_run_context,
)
from src.catalog_repository import CatalogRepository


class CatalogExportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.source_db = self.root / "private-streambase.sqlite"
        self.audio_root = self.root / "private-audio"
        self.audio_root.mkdir()
        (self.audio_root / "one.mp3").write_bytes(b"first-audio")
        (self.audio_root / "two.wav").write_bytes(b"second-audio")
        (self.audio_root / "not-referenced.mp3").write_bytes(b"must-not-export")
        self._create_source_database()

    def tearDown(self):
        self.tmp.cleanup()

    def _create_source_database(self):
        with closing(sqlite3.connect(self.source_db)) as connection:
            connection.executescript(
                """
                CREATE TABLE songs (
                    id INTEGER PRIMARY KEY,
                    title TEXT,
                    file_path TEXT UNIQUE,
                    release_status TEXT,
                    planned_release_date TEXT,
                    campaign_status TEXT,
                    created_at TEXT,
                    updated_at TEXT,
                    file_name TEXT,
                    artist_name TEXT,
                    spotify_url TEXT
                );
                CREATE TABLE song_audio_profiles (
                    id INTEGER PRIMARY KEY,
                    song_id INTEGER UNIQUE,
                    bpm REAL,
                    key TEXT,
                    genre_tags TEXT,
                    mood_tags TEXT,
                    energy TEXT,
                    danceability REAL,
                    instrumentation TEXT,
                    vocal_style TEXT,
                    lyrical_theme_notes TEXT,
                    reference_artists TEXT,
                    recommended_playlist_categories TEXT,
                    recommended_chartmetric_targets TEXT,
                    analysis_source TEXT,
                    notes TEXT,
                    updated_at TEXT,
                    source TEXT,
                    raw_analysis_json TEXT,
                    created_at TEXT
                );
                CREATE TABLE contacts (
                    id INTEGER PRIMARY KEY,
                    private_email TEXT,
                    private_notes TEXT
                );
                """
            )
            connection.executemany(
                """INSERT INTO songs
                   (id,title,file_path,release_status,planned_release_date,campaign_status,
                    created_at,updated_at,file_name,artist_name,spotify_url)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                [
                    (
                        1,
                        "Night Drive",
                        "/Users/private/one.mp3",
                        "released",
                        None,
                        "private-campaign",
                        "private-created",
                        "private-updated",
                        "one.mp3",
                        "Strange Hotels",
                        "https://private.invalid/spotify",
                    ),
                    (
                        2,
                        "Golden Hour",
                        "/Users/private/two.wav",
                        "unreleased",
                        "2026-08-01",
                        "private-campaign",
                        "private-created",
                        "private-updated",
                        "two.wav",
                        "Strange Hotels",
                        None,
                    ),
                ],
            )
            connection.execute(
                """INSERT INTO song_audio_profiles
                   (id,song_id,bpm,key,genre_tags,mood_tags,energy,danceability,
                    instrumentation,vocal_style,lyrical_theme_notes,reference_artists,
                    recommended_playlist_categories,recommended_chartmetric_targets,
                    analysis_source,notes,updated_at,source,raw_analysis_json,created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    1,
                    1,
                    113,
                    "G major",
                    "Disco;Rock",
                    "Driving;Uplifting",
                    "High",
                    0.81,
                    "Synthesizer;Drum Kit",
                    "Male vocal",
                    "private lyrics",
                    "private references",
                    "private playlists",
                    "private targets",
                    "cyanite",
                    "private notes",
                    "private updated",
                    "cyanite_artist_library",
                    json.dumps(
                        {
                            "emotional_profile": "Positive",
                            "keywords": ["Night", "Analog"],
                            "url": "https://vendor.invalid/private",
                            "private_payload": {"secret": True},
                        }
                    ),
                    "private created",
                ),
            )
            connection.execute(
                "INSERT INTO contacts (id,private_email,private_notes) VALUES (1,?,?)",
                ("person@example.com", "do not deploy"),
            )
            connection.commit()

    def _set_filename(self, song_id, file_name):
        with closing(sqlite3.connect(self.source_db)) as connection:
            connection.execute("UPDATE songs SET file_name=? WHERE id=?", (file_name, song_id))
            connection.commit()

    def test_export_contains_only_allowlisted_schema_rows_and_audio(self):
        output = self.root / "snapshot"
        result = export_catalog_snapshot(self.source_db, self.audio_root, output)

        self.assertEqual(result.track_count, 2)
        self.assertEqual(result.profile_count, 1)
        self.assertEqual(result.audio_file_count, 2)
        self.assertFalse(result.cloud_run_context)
        self.assertEqual(
            sorted(path.name for path in (output / "audio").iterdir()),
            ["song-1.mp3", "song-2.wav"],
        )
        self.assertEqual((output / "audio" / "song-1.mp3").read_bytes(), b"first-audio")
        self.assertEqual((output / "audio" / "song-2.wav").read_bytes(), b"second-audio")

        exported_db = output / "catalog.sqlite"
        with closing(sqlite3.connect(exported_db)) as connection:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            song_columns = [
                row[1] for row in connection.execute("PRAGMA table_info(songs)").fetchall()
            ]
            profile_columns = [
                row[1]
                for row in connection.execute(
                    "PRAGMA table_info(song_audio_profiles)"
                ).fetchall()
            ]
            raw_analysis = connection.execute(
                "SELECT raw_analysis_json FROM song_audio_profiles WHERE song_id=1"
            ).fetchone()[0]
            exported_file_names = [
                row[0]
                for row in connection.execute(
                    "SELECT file_name FROM songs ORDER BY id"
                ).fetchall()
            ]

        self.assertEqual(tables, {"songs", "song_audio_profiles"})
        self.assertEqual(
            song_columns,
            ["id", "title", "file_name", "release_status", "planned_release_date", "artist_name"],
        )
        self.assertEqual(
            profile_columns,
            [
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
            ],
        )
        self.assertEqual(
            json.loads(raw_analysis),
            {"emotional_profile": "Positive", "keywords": ["Night", "Analog"]},
        )
        self.assertEqual(exported_file_names, ["song-1.mp3", "song-2.wav"])
        exported_bytes = exported_db.read_bytes()
        for private_value in (
            b"person@example.com",
            b"do not deploy",
            b"private-campaign",
            b"vendor.invalid",
            b"private_payload",
            b"one.mp3",
            b"two.wav",
        ):
            self.assertNotIn(private_value, exported_bytes)

        repository = CatalogRepository(exported_db, output / "audio")
        tracks, total, has_more = repository.list_tracks(limit=10)
        self.assertEqual(total, 2)
        self.assertFalse(has_more)
        self.assertTrue(all(track["audioAvailable"] for track in tracks))
        self.assertEqual(tracks[0]["analysis"]["source"], "cyanite_artist_library")

    def test_rejects_unsafe_missing_and_duplicate_audio_without_output(self):
        cases = [
            ("unsafe", 1, "../outside.mp3", "Unsafe audio filename"),
            ("missing", 1, "missing.mp3", "Referenced audio is missing"),
            ("duplicate", 2, "one.mp3", "Duplicate audio filename"),
            ("case-duplicate", 2, "ONE.MP3", "Duplicate audio filename"),
        ]
        for label, song_id, file_name, expected_error in cases:
            with self.subTest(label=label):
                self._set_filename(song_id, file_name)
                output = self.root / f"failed-{label}"
                with self.assertRaisesRegex(CatalogSnapshotError, expected_error):
                    export_catalog_snapshot(self.source_db, self.audio_root, output)
                self.assertFalse(output.exists())
                self._set_filename(song_id, "one.mp3" if song_id == 1 else "two.wav")

    def test_rejects_symlink_audio(self):
        outside = self.root / "outside.mp3"
        outside.write_bytes(b"outside")
        link = self.audio_root / "linked.mp3"
        try:
            os.symlink(outside, link)
        except (OSError, NotImplementedError):
            self.skipTest("Symlinks are unavailable on this platform")
        self._set_filename(1, "linked.mp3")

        output = self.root / "symlink-output"
        with self.assertRaisesRegex(CatalogSnapshotError, "non-symlink"):
            export_catalog_snapshot(self.source_db, self.audio_root, output)
        self.assertFalse(output.exists())

    def test_existing_output_is_never_overwritten(self):
        output = self.root / "existing"
        output.mkdir()
        marker = output / "keep.txt"
        marker.write_text("keep", encoding="utf-8")

        with self.assertRaisesRegex(CatalogSnapshotError, "already exists"):
            export_catalog_snapshot(self.source_db, self.audio_root, output)
        self.assertEqual(marker.read_text(encoding="utf-8"), "keep")

    def test_cloud_run_context_contains_only_the_catalog_service(self):
        output = self.root / "cloud-run-context"
        result = prepare_cloud_run_context(self.source_db, self.audio_root, output)

        self.assertTrue(result.cloud_run_context)
        files = {
            path.relative_to(output).as_posix()
            for path in output.rglob("*")
            if path.is_file()
        }
        self.assertEqual(
            files,
            {
                "Dockerfile",
                "requirements.txt",
                "src/__init__.py",
                "src/catalog_api.py",
                "src/catalog_repository.py",
                "catalog_data/catalog.sqlite",
                "catalog_data/audio/song-1.mp3",
                "catalog_data/audio/song-2.wav",
            },
        )
        self.assertFalse(any(".env" in file_name for file_name in files))


if __name__ == "__main__":
    unittest.main()
