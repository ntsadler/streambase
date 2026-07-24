import hashlib
import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from starlette.testclient import TestClient

from src.catalog_api import create_app
from src.catalog_repository import AudioUnavailable, CatalogRepository


RAW_TOKEN = "showforge-test-token"
TOKEN_HASH = hashlib.sha256(RAW_TOKEN.encode("utf-8")).hexdigest()
AUTH = {"Authorization": f"Bearer {RAW_TOKEN}"}


class CatalogApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db_path = self.root / "streambase.sqlite"
        self.audio_root = self.root / "audio"
        self.audio_root.mkdir()
        self.first_audio = b"0123456789abcdef"
        (self.audio_root / "first.mp3").write_bytes(self.first_audio)
        (self.audio_root / "third.wav").write_bytes(b"RIFF-test-wave")
        self._create_catalog()
        self.repository = CatalogRepository(self.db_path, self.audio_root)
        self.client = TestClient(create_app(self.repository, token_hash=TOKEN_HASH))

    def tearDown(self):
        self.client.close()
        self.tmp.cleanup()

    def _create_catalog(self):
        with closing(sqlite3.connect(self.db_path)) as connection:
            connection.executescript(
                """
                CREATE TABLE songs (
                    id INTEGER PRIMARY KEY,
                    title TEXT,
                    file_path TEXT,
                    release_status TEXT,
                    planned_release_date TEXT,
                    file_name TEXT,
                    artist_name TEXT
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
                    analysis_source TEXT,
                    source TEXT,
                    raw_analysis_json TEXT
                );
                """
            )
            songs = [
                (1, "Night Drive", "/private/never-return-this.mp3", "released", None, "first.mp3", "Strange Hotels"),
                (3, "Golden Hour", "../../secret.wav", "unreleased", "2026-08-01", "missing.mp3", "Strange Hotels"),
                (7, "After Dark", "/another/private/path.wav", "released", None, "third.wav", "Strange Hotels"),
            ]
            connection.executemany(
                "INSERT INTO songs (id,title,file_path,release_status,planned_release_date,file_name,artist_name) VALUES (?,?,?,?,?,?,?)",
                songs,
            )
            profiles = [
                (
                    1,
                    1,
                    113,
                    "G major",
                    "Rock; 00; rock; 01",
                    "Driving; 02; Uplifting",
                    "High",
                    0.81,
                    "Synthesizer; 03; Drum Kit",
                    "Male vocal",
                    "cyanite",
                    "cyanite",
                    json.dumps(
                        {
                            "emotional_profile": "Positive",
                            "keywords": ["Night", "00", "night", "Analog"],
                            "url": "https://vendor.invalid/private",
                        }
                    ),
                ),
                (2, 3, 100, "A minor", "Pop", "Calm", "Medium", None, "Piano", "Instrumental", "manual", "manual", "{}"),
                (3, 7, 120, "D minor", "Electronic", "Dark", "High", 0.72, "Drums", "Male vocal", "cyanite", "cyanite", "{}"),
            ]
            connection.executemany(
                """INSERT INTO song_audio_profiles
                   (id,song_id,bpm,key,genre_tags,mood_tags,energy,danceability,instrumentation,vocal_style,analysis_source,source,raw_analysis_json)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                profiles,
            )
            connection.commit()

    def test_health_is_minimal_and_unauthenticated(self):
        response = self.client.get("/healthz")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True})
        self.assertEqual(response.headers["x-content-type-options"], "nosniff")

    def test_auth_fails_closed_and_rejects_bad_tokens(self):
        unconfigured = TestClient(create_app(self.repository, token_hash=""))
        try:
            response = unconfigured.get("/v1/tracks")
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.json()["error"]["code"], "service_not_configured")
        finally:
            unconfigured.close()

        missing = self.client.get("/v1/tracks")
        wrong = self.client.get("/v1/tracks", headers={"Authorization": "Bearer wrong"})
        self.assertEqual(missing.status_code, 401)
        self.assertEqual(wrong.status_code, 401)
        self.assertEqual(missing.json(), wrong.json())
        self.assertEqual(missing.headers["www-authenticate"], "Bearer")

    def test_keyset_pagination_search_and_safe_contract(self):
        first = self.client.get("/v1/tracks?limit=2", headers=AUTH)
        self.assertEqual(first.status_code, 200)
        body = first.json()
        self.assertEqual([item["id"] for item in body["items"]], [1, 3])
        self.assertEqual(body["total"], 3)
        self.assertIsInstance(body["nextCursor"], str)

        second = self.client.get(
            "/v1/tracks",
            params={"limit": 2, "cursor": body["nextCursor"]},
            headers=AUTH,
        )
        self.assertEqual([item["id"] for item in second.json()["items"]], [7])
        self.assertIsNone(second.json()["nextCursor"])

        item = body["items"][0]
        self.assertEqual(
            set(item),
            {"id", "ref", "title", "artistName", "releaseStatus", "plannedReleaseDate", "audioAvailable", "analysis"},
        )
        self.assertEqual(item["ref"], "streambase:song:1")
        self.assertEqual(item["analysis"]["genres"], ["Rock"])
        self.assertEqual(item["analysis"]["moods"], ["Driving", "Uplifting"])
        self.assertEqual(item["analysis"]["keywords"], ["Night", "Analog"])
        serialized = json.dumps(body)
        self.assertNotIn("file_path", serialized)
        self.assertNotIn("never-return-this", serialized)
        self.assertNotIn("vendor.invalid", serialized)

        filtered = self.client.get("/v1/tracks", params={"q": "After"}, headers=AUTH)
        self.assertEqual(filtered.json()["total"], 1)
        self.assertEqual(filtered.json()["items"][0]["id"], 7)

    def test_cursor_is_signed_and_bound_to_search(self):
        first = self.client.get("/v1/tracks", params={"limit": 1, "q": "Strange"}, headers=AUTH).json()
        cursor = first["nextCursor"]
        self.assertIsNotNone(cursor)

        tampered = cursor[:-1] + ("A" if cursor[-1] != "A" else "B")
        tampered_response = self.client.get("/v1/tracks", params={"cursor": tampered, "q": "Strange"}, headers=AUTH)
        rebound_response = self.client.get("/v1/tracks", params={"cursor": cursor, "q": "Night"}, headers=AUTH)
        self.assertEqual(tampered_response.status_code, 400)
        self.assertEqual(rebound_response.status_code, 400)
        self.assertEqual(rebound_response.json()["error"]["code"], "invalid_cursor")

        mood_filtered = self.client.get("/v1/tracks", params={"mood": "Driving", "energy": "High"}, headers=AUTH)
        self.assertEqual([item["id"] for item in mood_filtered.json()["items"]], [1])

    def test_unknown_and_repeated_query_params_are_rejected(self):
        unknown = self.client.get("/v1/tracks?sort=title", headers=AUTH)
        repeated = self.client.get("/v1/tracks?q=Night&q=Dark", headers=AUTH)
        too_long = self.client.get("/v1/tracks", params={"q": "x" * 101}, headers=AUTH)

        self.assertEqual(unknown.status_code, 400)
        self.assertEqual(repeated.status_code, 400)
        self.assertEqual(too_long.status_code, 400)

    def test_detail_and_not_found_use_safe_json_errors(self):
        response = self.client.get("/v1/tracks/1", headers=AUTH)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["track"]["id"], 1)
        self.assertIsNone(response.json()["track"]["plannedReleaseDate"])

        missing = self.client.get("/v1/tracks/999", headers=AUTH)
        unknown_route = self.client.get("/not-a-route")
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(missing.json()["error"]["code"], "track_not_found")
        self.assertEqual(unknown_route.json()["error"]["code"], "not_found")

    def test_repository_connection_is_actually_read_only(self):
        connection = self.repository._connect()
        try:
            self.assertEqual(connection.execute("PRAGMA query_only").fetchone()[0], 1)
            with self.assertRaises(sqlite3.OperationalError):
                connection.execute("CREATE TABLE forbidden_write (id INTEGER)")
        finally:
            connection.close()

    def test_audio_resolution_rejects_paths_symlinks_and_missing_files(self):
        with self.assertRaises(AudioUnavailable):
            self.repository._resolve_audio_name("../outside.mp3")
        with self.assertRaises(AudioUnavailable):
            self.repository._resolve_audio_name("nested/track.mp3")
        with self.assertRaises(AudioUnavailable):
            self.repository._resolve_audio_name("first.mp3\x00")
        with self.assertRaises(AudioUnavailable):
            self.repository._resolve_audio_name("track.flac")
        with self.assertRaises(AudioUnavailable):
            self.repository._resolve_audio_name("missing.mp3")

        outside = self.root / "outside.mp3"
        outside.write_bytes(b"outside")
        link = self.audio_root / "linked.mp3"
        try:
            os.symlink(outside, link)
        except (OSError, NotImplementedError):
            self.skipTest("Symlinks are unavailable on this platform")
        with self.assertRaises(AudioUnavailable):
            self.repository._resolve_audio_name("linked.mp3")

    def test_audio_get_head_and_ranges(self):
        full = self.client.get("/v1/tracks/1/audio", headers=AUTH)
        self.assertEqual(full.status_code, 200)
        self.assertEqual(full.content, self.first_audio)
        self.assertEqual(full.headers["content-type"], "audio/mpeg")
        self.assertEqual(full.headers["accept-ranges"], "bytes")
        self.assertEqual(full.headers["x-content-type-options"], "nosniff")
        self.assertEqual(full.headers["vary"], "Authorization")
        self.assertNotIn("content-disposition", full.headers)

        head = self.client.head("/v1/tracks/1/audio", headers=AUTH)
        self.assertEqual(head.status_code, 200)
        self.assertEqual(head.content, b"")
        self.assertEqual(int(head.headers["content-length"]), len(self.first_audio))

        partial = self.client.get("/v1/tracks/1/audio", headers={**AUTH, "Range": "bytes=2-5"})
        self.assertEqual(partial.status_code, 206)
        self.assertEqual(partial.content, self.first_audio[2:6])
        self.assertEqual(partial.headers["content-range"], f"bytes 2-5/{len(self.first_audio)}")

        suffix = self.client.get("/v1/tracks/1/audio", headers={**AUTH, "Range": "bytes=-4"})
        self.assertEqual(suffix.status_code, 206)
        self.assertEqual(suffix.content, self.first_audio[-4:])

        unsatisfiable = self.client.get("/v1/tracks/1/audio", headers={**AUTH, "Range": "bytes=999-1000"})
        self.assertEqual(unsatisfiable.status_code, 416)
        self.assertEqual(unsatisfiable.headers["content-range"], f"bytes */{len(self.first_audio)}")


if __name__ == "__main__":
    unittest.main()
