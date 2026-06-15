import tempfile
import unittest
from pathlib import Path

from src.chartmetric import ChartmetricAPI, extract_playlist_items, normalize_chartmetric_playlist
from src.chartmetric_mining import chartmetric_queries_from_profile, run_chartmetric_mining
from src.database import get_mining_jobs, init_db


class FakeChartmetric(ChartmetricAPI):
    def __init__(self, configured=True):
        self.api_token = "token" if configured else ""
        self.base_url = "https://example.test"
        self.timeout = 1

    def search_playlists(self, query, limit=25, offset=0):
        return {
            "playlists": [
                {
                    "id": "cm1",
                    "name": f"{query} Playlist",
                    "url": "https://open.spotify.com/playlist/cm1",
                    "followers": 5000,
                    "description": "A test playlist",
                }
            ]
        }


class ChartmetricMiningTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tmp.name) / "streambase.sqlite")
        init_db(self.db_path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_query_planner_uses_profile_targets(self):
        profile = {
            "profile_name": "Artist Sound Profile",
            "core_genre_tags": ["indie dance", "psych pop"],
            "core_mood_tags": ["dreamy"],
            "strongest_reference_artists": ["Artist A"],
            "track_examples": ["Track 01"],
        }

        queries = chartmetric_queries_from_profile(profile, limit=10)

        self.assertTrue(any("indie dance" in q["query"] for q in queries))
        self.assertTrue(any(q["type"] == "artist" and q["query"] == "Artist A" for q in queries))

    def test_dry_run_creates_planned_job_without_token(self):
        profile = {"profile_name": "Artist Sound Profile", "core_genre_tags": ["indie dance"]}

        result = run_chartmetric_mining(profile, client=FakeChartmetric(configured=False), dry_run=None, db_path=self.db_path)

        self.assertTrue(result["dry_run"])
        self.assertGreater(result["job_id"], 0)
        self.assertEqual(get_mining_jobs(self.db_path)[0]["status"], "planned")

    def test_live_run_normalizes_and_saves_playlists(self):
        profile = {"profile_name": "Artist Sound Profile", "core_genre_tags": ["indie dance"]}

        result = run_chartmetric_mining(profile, client=FakeChartmetric(configured=True), dry_run=False, max_queries=1, db_path=self.db_path)

        self.assertFalse(result["dry_run"])
        self.assertEqual(result["saved_count"], 1)

    def test_normalize_chartmetric_playlist(self):
        playlist = normalize_chartmetric_playlist({"id": "123", "name": "Test", "followers": 1200}, "indie dance")

        self.assertEqual(playlist["chartmetric_playlist_id"], "123")
        self.assertEqual(playlist["playlist_name"], "Test")
        self.assertEqual(playlist["search_query"], "indie dance")

    def test_extract_playlist_items_handles_nested_shapes(self):
        self.assertEqual(extract_playlist_items({"data": {"results": [{"id": 1}]}}), [{"id": 1}])


if __name__ == "__main__":
    unittest.main()
