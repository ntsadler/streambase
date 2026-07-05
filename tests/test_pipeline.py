import unittest

from src.pipeline import apply_discovery_targeting_score, normalize_song_context


class PipelineTests(unittest.TestCase):
    def test_normalize_song_context_accepts_dict(self):
        context = {"title": "Song", "spotify_url": "https://open.spotify.com/track/test"}

        self.assertEqual(normalize_song_context(context), context)

    def test_normalize_song_context_parses_editor_string(self):
        context = "{'title': 'Song', 'artist': 'Artist', 'release_status': 'released'}"

        self.assertEqual(
            normalize_song_context(context),
            {"title": "Song", "artist": "Artist", "release_status": "released"},
        )

    def test_normalize_song_context_ignores_plain_text(self):
        self.assertEqual(normalize_song_context("Song"), {})

    def test_apply_discovery_targeting_score_lifts_song_specific_fit(self):
        scored = {
            "final_score": 42,
            "priority": "weak fit",
            "confidence_score": 45,
            "evidence": ["contact path"],
            "breakdown": {"contactability": 75},
        }
        playlist = {
            "candidate_fit_score": 88,
            "curator_target_score": 30,
            "discovery_intent_hits": ["emerging artists"],
            "submission_ready_hits": ["submit music"],
        }

        result = apply_discovery_targeting_score(scored, playlist)

        self.assertGreater(result["final_score"], 65)
        self.assertEqual(result["priority"], "strong fit")
        self.assertIn("emerging artist discovery intent", result["evidence"])


if __name__ == "__main__":
    unittest.main()
