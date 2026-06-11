import unittest

from src.song_analyzer import analyze_song_fit, score_spotify_playlist_candidates


class SongAnalyzerTests(unittest.TestCase):
    def test_song_fit_recommends_matching_lane_from_spotify_metadata(self):
        meta = {
            "title": "Night Drive",
            "artist": "Test Artist",
            "reference_artists": "MGMT; LCD Soundsystem",
            "descriptors": "indie dance; electronic; synth",
            "release_date": "2026-05-01",
            "duration_ms": 210000,
            "popularity": 30,
        }
        result = analyze_song_fit(None, saved_playlists=[], spotify_track=meta)

        self.assertEqual(result["recommended_playlist_lanes"][0]["lane"], "Indie electronic / alt dance")
        self.assertFalse(result["release_guidance"]["exclude_new_release_playlists"])

    def test_old_song_excludes_new_release_playlists(self):
        meta = {
            "title": "Old Song",
            "artist": "Test Artist",
            "reference_artists": "MGMT; LCD Soundsystem",
            "descriptors": "indie dance; electronic",
            "release_date": "2024-01-01",
            "duration_ms": 210000,
            "popularity": 35,
        }
        playlists = [
            {
                "name": "New Music Friday Indie",
                "curator_name": "A",
                "url": "https://open.spotify.com/playlist/new",
                "related_artists": "MGMT",
                "spotify_description": "new releases fresh drops",
                "final_score": 90,
            },
            {
                "name": "Indie Dance Classics",
                "curator_name": "B",
                "url": "https://open.spotify.com/playlist/evergreen",
                "related_artists": "MGMT",
                "spotify_description": "indie dance electronic favorites",
                "final_score": 80,
            },
        ]

        result = analyze_song_fit(None, saved_playlists=playlists, spotify_track=meta)

        self.assertTrue(result["release_guidance"]["exclude_new_release_playlists"])
        self.assertEqual([m["playlist_name"] for m in result["saved_playlist_matches"]], ["Indie Dance Classics"])
        self.assertTrue(all("evergreen" in s["search_query"] for s in result["discovery_searches"]))

    def test_no_release_date_does_not_exclude_new_release_context(self):
        meta = {
            "title": "Unknown Date Song",
            "artist": "Test Artist",
            "reference_artists": "MGMT",
            "descriptors": "fresh indie electronic",
        }
        result = analyze_song_fit(None, saved_playlists=[], spotify_track=meta)

        self.assertEqual(result["release_guidance"]["release_age_label"], "unknown")
        self.assertFalse(result["release_guidance"]["exclude_new_release_playlists"])

    def test_candidate_scoring_dedupes_and_filters_new_release_for_old_song(self):
        meta = {
            "title": "Old Song",
            "artist": "Test Artist",
            "reference_artists": "MGMT; LCD Soundsystem",
            "descriptors": "indie dance; electronic",
            "release_date": "2024-01-01",
        }
        fit = analyze_song_fit(None, saved_playlists=[], spotify_track=meta)
        candidates = [
            {
                "playlist_name": "New Music Friday Indie",
                "playlist_url": "https://open.spotify.com/playlist/new",
                "curator_name": "A",
                "follower_count": 5000,
                "related_artists": "MGMT",
                "spotify_description": "new releases fresh drops",
                "search_query": "new music",
            },
            {
                "playlist_name": "Indie Dance Evergreen",
                "playlist_url": "https://open.spotify.com/playlist/evergreen",
                "curator_name": "B",
                "follower_count": 2000,
                "related_artists": "MGMT",
                "spotify_description": "indie dance favorites",
                "search_query": "evergreen indie dance",
            },
        ]
        existing = [{"url": "https://open.spotify.com/playlist/evergreen"}]

        scored = score_spotify_playlist_candidates(fit, candidates, existing)

        self.assertEqual(len(scored), 1)
        self.assertEqual(scored[0]["playlist_name"], "Indie Dance Evergreen")
        self.assertTrue(scored[0]["already_in_crm"])
        self.assertGreater(scored[0]["candidate_fit_score"], 0)

    def test_reference_tracks_feed_lane_and_search_context(self):
        meta = {
            "title": "My Track",
            "artist": "Test Artist",
            "release_date": "2026-05-01",
        }
        reference_tracks = [
            {
                "title": "Reference One",
                "artist": "LCD Soundsystem",
                "reference_artists": "LCD Soundsystem",
                "descriptors": "indie dance; electronic; synth",
                "popularity": 55,
            },
            {
                "title": "Reference Two",
                "artist": "MGMT",
                "reference_artists": "MGMT",
                "descriptors": "indie pop; synth",
                "popularity": 60,
            },
        ]

        result = analyze_song_fit(None, saved_playlists=[], spotify_track=meta, reference_tracks=reference_tracks)

        self.assertEqual(result["recommended_playlist_lanes"][0]["lane"], "Indie electronic / alt dance")
        self.assertIn("MGMT", result["reference_track_summary"]["reference_artists"])
        self.assertTrue(any("MGMT" in s["search_query"] for s in result["discovery_searches"]))

    def test_cyanite_tags_feed_lane_context(self):
        meta = {
            "title": "Soft Track",
            "artist": "Test Artist",
            "release_date": "2026-05-01",
        }
        cyanite = {
            "source": "cyanite",
            "genres": ["bedroom pop"],
            "moods": ["dreamy", "chill"],
            "instruments": ["soft synth"],
            "keywords": [],
            "energy": "low",
            "descriptors": "bedroom pop; dreamy; chill; soft synth",
        }

        result = analyze_song_fit(None, saved_playlists=[], spotify_track=meta, cyanite_profile=cyanite)

        self.assertEqual(result["recommended_playlist_lanes"][0]["lane"], "Bedroom pop / chill indie")
        self.assertIn("bedroom pop", result["song"]["descriptors"])
        self.assertEqual(result["cyanite_summary"]["source"], "cyanite")


if __name__ == "__main__":
    unittest.main()
