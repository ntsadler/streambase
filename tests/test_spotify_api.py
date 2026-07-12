import unittest
from unittest.mock import Mock
from unittest.mock import patch

import requests

from src.spotify_api import SpotifyAPI, extract_playlist_id, extract_track_id, search_spotify_playlists, search_spotify_playlists_multi_market


class SpotifyApiTests(unittest.TestCase):
    def test_extract_ids_from_links(self):
        self.assertEqual(extract_track_id("https://open.spotify.com/track/abc123?si=x"), "abc123")
        self.assertEqual(extract_playlist_id("https://open.spotify.com/playlist/pl123?si=x"), "pl123")

    @patch("src.spotify_api.requests.get")
    def test_get_playlist_tracks_paginates(self, mock_get):
        first = Mock()
        first.raise_for_status.return_value = None
        first.json.return_value = {
            "items": [{"track": {"id": "one", "name": "One", "artists": []}}],
            "next": "https://api.spotify.com/v1/playlists/pl123/tracks?offset=100",
        }
        second = Mock()
        second.raise_for_status.return_value = None
        second.json.return_value = {
            "items": [{"track": {"id": "two", "name": "Two", "artists": []}}],
            "next": None,
        }
        mock_get.side_effect = [first, second]

        client = SpotifyAPI("id", "secret")
        client._token = "token"
        tracks = client.get_playlist_tracks("https://open.spotify.com/playlist/pl123")

        self.assertEqual([item["track"]["id"] for item in tracks], ["one", "two"])
        self.assertEqual(mock_get.call_count, 2)
        self.assertIn("/playlists/pl123/tracks", mock_get.call_args_list[0].args[0])

    @patch("src.spotify_api.requests.get")
    def test_get_playlist_tracks_uses_items_endpoint_with_user_token(self, mock_get):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "items": [{"track": {"id": "one", "name": "One", "artists": []}}],
            "next": None,
        }
        mock_get.return_value = response

        with patch.dict("os.environ", {"SPOTIFY_REFRESH_TOKEN": "refresh"}, clear=False):
            client = SpotifyAPI("id", "secret")
            client._user_token = "user-token"
            tracks = client.get_playlist_tracks("https://open.spotify.com/playlist/pl123")

        self.assertEqual([item["track"]["id"] for item in tracks], ["one"])
        self.assertIn("/playlists/pl123/items", mock_get.call_args.args[0])

    @patch("src.spotify_api.SpotifyAPI")
    def test_search_spotify_playlists_dedupes_results(self, mock_api):
        client = mock_api.return_value
        client.configured = True
        client.search_and_enrich_playlists.side_effect = [
            [
                {"playlist_name": "A", "playlist_url": "https://open.spotify.com/playlist/1"},
                {"playlist_name": "A duplicate", "playlist_url": "https://open.spotify.com/playlist/1"},
            ],
            [{"playlist_name": "B", "playlist_url": "https://open.spotify.com/playlist/2"}],
        ]

        result = search_spotify_playlists(["indie dance", "alt dance"], 5, "US")

        self.assertTrue(result["ok"])
        self.assertEqual([p["playlist_name"] for p in result["playlists"]], ["A", "B"])

    @patch("src.spotify_api.SpotifyAPI")
    def test_search_spotify_playlists_handles_api_errors(self, mock_api):
        client = mock_api.return_value
        client.configured = True
        client.search_and_enrich_playlists.side_effect = requests.RequestException("rate limited")

        result = search_spotify_playlists(["indie dance"], 5, "US")

        self.assertFalse(result["ok"])
        self.assertIn("rate limited", result["error"])
        self.assertEqual(result["playlists"], [])

    @patch("src.spotify_api.SpotifyAPI")
    def test_search_spotify_playlists_requires_credentials(self, mock_api):
        client = mock_api.return_value
        client.configured = False

        result = search_spotify_playlists(["indie dance"], 5, "US")

        self.assertFalse(result["ok"])
        self.assertIn("credentials", result["error"])

    @patch("src.spotify_api.search_spotify_playlists")
    def test_multi_market_search_dedupes_across_english_markets(self, mock_search):
        mock_search.side_effect = [
            {"ok": True, "error": "", "playlists": [{"playlist_name": "A", "playlist_url": "https://open.spotify.com/playlist/1"}]},
            {"ok": True, "error": "", "playlists": [{"playlist_name": "A UK", "playlist_url": "https://open.spotify.com/playlist/1"}, {"playlist_name": "B", "playlist_url": "https://open.spotify.com/playlist/2"}]},
        ]

        result = search_spotify_playlists_multi_market(["indie dance"], 5, ["US", "GB"])

        self.assertTrue(result["ok"])
        self.assertEqual(result["markets"], ["US", "GB"])
        self.assertEqual([p["playlist_name"] for p in result["playlists"]], ["A", "B"])
        self.assertEqual(result["playlists"][0]["spotify_market"], "US")
        self.assertEqual(result["playlists"][1]["spotify_market"], "GB")


if __name__ == "__main__":
    unittest.main()
