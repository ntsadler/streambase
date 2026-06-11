import unittest
from unittest.mock import patch

import requests

from src.spotify_api import extract_playlist_id, extract_track_id, search_spotify_playlists


class SpotifyApiTests(unittest.TestCase):
    def test_extract_ids_from_links(self):
        self.assertEqual(extract_track_id("https://open.spotify.com/track/abc123?si=x"), "abc123")
        self.assertEqual(extract_playlist_id("https://open.spotify.com/playlist/pl123?si=x"), "pl123")

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


if __name__ == "__main__":
    unittest.main()
