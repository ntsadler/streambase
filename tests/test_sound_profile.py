import unittest

from src.mining_targets import build_chartmetric_targets
from src.sound_profile import build_artist_sound_profile


class SoundProfileTests(unittest.TestCase):
    def test_build_artist_sound_profile_aggregates_catalog_traits(self):
        songs = [
            {
                "title": "Song A",
                "bpm": 120,
                "danceability": 0.7,
                "genre_tags": "indie dance; psych pop",
                "mood_tags": "late-night; euphoric",
                "energy": "high",
                "instrumentation": "synth; guitar",
                "vocal_style": "male vocal",
                "reference_artists": "MGMT; LCD Soundsystem",
            },
            {
                "title": "Song B",
                "bpm": 124,
                "danceability": 0.8,
                "genre_tags": "indie dance; alternative electronic",
                "mood_tags": "late-night; dreamy",
                "energy": "high",
                "instrumentation": "synth; drum machine",
                "vocal_style": "male vocal",
                "reference_artists": "Hot Chip; LCD Soundsystem",
            },
        ]

        refs = [
            {"artist_name": "MGMT", "source": "chartmetric", "confidence_score": 87, "approved_by_user": 0, "rejected_by_user": 0},
            {"artist_name": "LCD Soundsystem", "source": "manual", "confidence_score": 100, "approved_by_user": 1, "rejected_by_user": 0},
        ]

        profile = build_artist_sound_profile(songs, artist_references=refs)

        self.assertEqual(profile["song_count"], 2)
        self.assertEqual(profile["average_bpm"], 122)
        self.assertEqual(profile["core_genre_tags"][0], "indie dance")
        self.assertEqual(profile["core_mood_tags"][0], "late-night")
        self.assertIn("LCD Soundsystem", profile["strongest_reference_artists"])
        self.assertEqual(profile["strongest_reference_artists"][0], "LCD Soundsystem")
        self.assertIn("not the primary source", profile["reference_artist_policy"])
        self.assertTrue(profile["playlist_search_phrases"])
        self.assertIn("chartmetric_mining_targets", profile)

    def test_rejected_reference_artists_are_excluded(self):
        profile = build_artist_sound_profile(
            [{"title": "Song", "genre_tags": "indie dance", "mood_tags": "dreamy"}],
            artist_references=[
                {"artist_name": "Rejected Artist", "source": "spotify", "confidence_score": 95, "rejected_by_user": 1},
                {"artist_name": "Approved Artist", "source": "manual", "confidence_score": 80, "approved_by_user": 1},
            ],
        )

        self.assertIn("Approved Artist", profile["strongest_reference_artists"])
        self.assertNotIn("Rejected Artist", profile["strongest_reference_artists"])

    def test_chartmetric_targets_include_reference_pairs_and_exclusions(self):
        profile = {
            "core_genre_tags": ["indie dance", "psych pop"],
            "core_mood_tags": ["late-night", "dreamy"],
            "strongest_reference_artists": ["MGMT", "LCD Soundsystem", "Hot Chip"],
            "track_examples": ["Song A"],
        }

        targets = build_chartmetric_targets(profile)

        self.assertIn("MGMT", targets["reference_artists_to_search"])
        self.assertIn("playlists containing MGMT + LCD Soundsystem", targets["chartmetric_queries"])
        self.assertEqual(targets["playlist_follower_range"]["min"], 1000)
        self.assertTrue(any("exclude Spotify editorial" in rule for rule in targets["playlist_exclusion_rules"]))


if __name__ == "__main__":
    unittest.main()
