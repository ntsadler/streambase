import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.chartmetric import ChartmetricAPI, extract_playlist_items, normalize_chartmetric_playlist
from src.chartmetric_mining import chartmetric_queries_from_profile, run_chartmetric_mining
from src.database import get_api_usage_events, get_mined_playlists, get_mining_jobs, get_mining_query_runs, init_db
from src.mining_targets import build_catalog_mining_profile, build_chartmetric_targets
from src.viberate import ViberateAPI, normalize_viberate_playlist
from src.viberate_mining import _viberate_sleep_seconds, run_viberate_mining, viberate_queries_from_profile


class FakeChartmetric(ChartmetricAPI):
    def __init__(self, configured=True):
        self.api_token = "token" if configured else ""
        self.refresh_token = ""
        self.base_url = "https://example.test"
        self.timeout = 1

    def search_playlists(self, query, limit=25, offset=0):
        return {
            "playlists": [
                {
                    "id": "cm1",
                    "name": f"{query} Playlist",
                    "url": "https://open.spotify.com/playlist/cm1",
                    "followers": 500,
                    "description": "A test indie dance playlist",
                },
                {
                    "id": "cm2",
                    "name": f"{query} Large Playlist",
                    "url": "https://open.spotify.com/playlist/cm2",
                    "followers": 5000,
                    "description": "A test indie dance playlist",
                }
            ]
        }


class FakeViberate(ViberateAPI):
    def __init__(self, configured=True):
        self.api_key = "token" if configured else ""
        self.base_url = "https://example.test"
        self.timeout = 1
        self.last_status_code = 200
        self.last_response_headers = {"X-RateLimit-Remaining": "99"}

    def search_playlists(self, query, limit=25, offset=0):
        return {
            "data": {
                "playlists": [
                    {
                        "viberate_playlist_id": "vb1",
                        "playlist_name": f"{query} Viberate Playlist",
                        "playlist_url": "https://open.spotify.com/playlist/vb1",
                        "follower_count": 450,
                        "spotify_description": "A test indie dance playlist",
                    }
                ]
            }
        }


class ChartmetricMiningTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tmp.name) / "streambase.sqlite")
        init_db(self.db_path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_chartmetric_refresh_token_mints_cached_access_token(self):
        class FakeResponse:
            status_code = 200
            headers = {"X-RateLimit-Remaining": "24"}

            def raise_for_status(self):
                return None

            def json(self):
                return {"token": "access-token", "expires_in": 3600}

        with patch("src.chartmetric.requests.post", return_value=FakeResponse()) as post:
            client = ChartmetricAPI(refresh_token="refresh-token", base_url="https://api.chartmetric.com/api")
            self.assertTrue(client.configured)
            self.assertEqual(client._headers()["Authorization"], "Bearer access-token")
            self.assertEqual(client._headers()["Authorization"], "Bearer access-token")

        self.assertEqual(post.call_count, 1)
        self.assertEqual(post.call_args.kwargs["json"], {"refreshtoken": "refresh-token"})

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
        self.assertEqual(result["filtered_out_count"], 1)
        mined = get_mined_playlists(result["job_id"], self.db_path)
        self.assertEqual(mined[0]["follower_tier"], "under_1000")

    def test_run_pauses_on_request_budget_and_resumes_remaining_queries(self):
        profile = {"profile_name": "Artist Sound Profile", "core_genre_tags": ["indie dance"], "core_mood_tags": ["dreamy"]}

        first = run_chartmetric_mining(
            profile,
            client=FakeChartmetric(configured=True),
            dry_run=False,
            max_queries=2,
            max_requests_per_run=1,
            db_path=self.db_path,
        )

        self.assertTrue(first["paused"])
        self.assertEqual(first["request_count"], 1)
        self.assertEqual(first["saved_count"], 1)
        first_runs = get_mining_query_runs(first["job_id"], db_path=self.db_path)
        self.assertEqual([row["status"] for row in first_runs], ["completed", "planned"])

        resumed = run_chartmetric_mining(
            profile,
            client=FakeChartmetric(configured=True),
            dry_run=False,
            max_queries=2,
            max_requests_per_run=10,
            resume_job_id=first["job_id"],
            db_path=self.db_path,
        )

        self.assertFalse(resumed["paused"])
        self.assertEqual(resumed["job_id"], first["job_id"])
        self.assertEqual(resumed["saved_count"], 2)
        self.assertEqual([row["status"] for row in get_mining_query_runs(first["job_id"], db_path=self.db_path)], ["completed", "completed"])
        self.assertEqual(len(get_api_usage_events("chartmetric", self.db_path)), 2)

    def test_default_targets_focus_under_1000_followers(self):
        targets = build_chartmetric_targets({"profile_name": "Artist Sound Profile", "core_genre_tags": ["indie dance"]})

        self.assertEqual(targets["playlist_follower_range"], {"min": 50, "max": 999})

    def test_catalog_profile_uses_released_catalog_terms(self):
        profile = build_catalog_mining_profile([
            {"title": "First", "release_status": "released", "genre_tags": "indie dance; synth pop", "mood_tags": "dreamy", "reference_artists": "Artist A", "recommended_playlist_categories": "late night indie"},
            {"title": "Second", "release_status": "unreleased", "genre_tags": "metal", "mood_tags": "angry", "reference_artists": "Artist B"},
        ])

        self.assertEqual(profile["song_count"], 1)
        self.assertIn("indie dance", profile["core_genre_tags"])
        self.assertNotIn("metal", profile["core_genre_tags"])
        self.assertEqual(profile["chartmetric_mining_targets"]["playlist_follower_range"]["max"], 999)

    def test_normalize_chartmetric_playlist(self):
        playlist = normalize_chartmetric_playlist({"id": "123", "name": "Test", "followers": 1200}, "indie dance")

        self.assertEqual(playlist["chartmetric_playlist_id"], "123")
        self.assertEqual(playlist["playlist_name"], "Test")
        self.assertEqual(playlist["search_query"], "indie dance")

    def test_extract_playlist_items_handles_nested_shapes(self):
        self.assertEqual(extract_playlist_items({"data": {"results": [{"id": 1}]}}), [{"id": 1}])

    def test_viberate_lane_uses_separate_source(self):
        profile = {"profile_name": "Artist Sound Profile", "core_genre_tags": ["indie dance"]}

        result = run_viberate_mining(profile, client=FakeViberate(configured=True), dry_run=False, max_queries=1, sleep_seconds=0, db_path=self.db_path)

        self.assertEqual(result["saved_count"], 1)
        jobs = get_mining_jobs(self.db_path)
        self.assertEqual(jobs[0]["source"], "viberate")
        mined = get_mined_playlists(result["job_id"], self.db_path)
        self.assertEqual(mined[0]["source"], "viberate")
        self.assertEqual(mined[0]["source_playlist_id"], "vb1")
        self.assertEqual(len(get_api_usage_events("viberate", self.db_path)), 1)

    def test_normalize_viberate_playlist(self):
        playlist = normalize_viberate_playlist({"viberate_playlist_id": "vb1", "playlist_name": "Test", "follower_count": 100}, "indie dance")

        self.assertEqual(playlist["source"], "viberate")
        self.assertEqual(playlist["source_playlist_id"], "vb1")
        self.assertEqual(playlist["playlist_name"], "Test")

    def test_viberate_defaults_to_trial_safe_three_requests_per_minute(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(_viberate_sleep_seconds(None), 20.0)

    def test_viberate_queries_use_playlist_title_search_phrasing(self):
        profile = {
            "profile_name": "Artist Sound Profile",
            "core_genre_tags": ["Pop"],
            "core_mood_tags": ["Uplifting"],
            "cyanite_seed_artists": ["Tame Impala"],
        }

        queries = viberate_queries_from_profile(profile, limit=8)

        self.assertEqual(queries[0], {"type": "artist_playlist", "query": "Tame Impala"})
        self.assertIn({"type": "artist_playlist", "query": "Tame Impala | offset=20"}, queries)
        self.assertIn({"type": "chart", "query": "genre=Pop; playlist_type=Indie Curator"}, queries)
        self.assertIn({"type": "query", "query": "Pop playlist"}, queries)
        self.assertFalse(any("playlists tagged" in item["query"].lower() for item in queries))


if __name__ == "__main__":
    unittest.main()
