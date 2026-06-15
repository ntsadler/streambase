import unittest

from src.release_prep import build_campaign_brief, campaign_readiness, infer_playlist_categories


class ReleasePrepTests(unittest.TestCase):
    def test_campaign_brief_includes_song_dna_and_chartmetric_targets(self):
        song = {
            "title": "Track 07",
            "release_status": "unreleased",
            "planned_release_date": "",
            "bpm": 122,
            "key": "A minor",
            "genre_tags": "indie dance; psych pop; synth pop",
            "mood_tags": "dreamy; energetic",
            "energy": "high",
            "danceability": 0.78,
            "instrumentation": "synth-driven; drum machine",
            "vocal_style": "male vocal",
            "lyrical_theme_notes": "night drive escape",
            "reference_artists": "MGMT; LCD Soundsystem; Hot Chip; Roosevelt",
            "recommended_playlist_categories": "",
        }

        brief = build_campaign_brief(song)

        self.assertEqual(brief["song_title"], "Track 07")
        self.assertIn("indie dance", brief["song_dna_summary"]["genres"])
        self.assertIn("MGMT", brief["best_reference_artists"])
        self.assertIn("playlists containing MGMT + LCD Soundsystem", brief["best_chartmetric_mining_queries"])
        self.assertEqual(brief["ideal_playlist_follower_range"]["max"], 75000)
        self.assertTrue(brief["copy_direction"]["email"])

    def test_infer_playlist_categories_from_song_traits(self):
        song = {"genre_tags": "indie dance; psych pop", "mood_tags": "dreamy", "energy": "energetic"}

        categories = infer_playlist_categories(song)

        self.assertIn("indie dance discovery", categories)
        self.assertIn("dreamy playlist", categories)
        self.assertIn("energetic independent playlist", categories)

    def test_campaign_readiness_moves_forward_with_profile_data(self):
        self.assertEqual(campaign_readiness({}), "needs_profile")
        self.assertEqual(campaign_readiness({"genre_tags": "indie", "mood_tags": "dreamy"}), "profile_ready")
        self.assertEqual(
            campaign_readiness({"genre_tags": "indie", "mood_tags": "dreamy", "reference_artists": "MGMT"}),
            "mining_ready",
        )


if __name__ == "__main__":
    unittest.main()
