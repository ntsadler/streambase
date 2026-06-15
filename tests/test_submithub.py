import unittest

from src.scorer import contactability_score, score_playlist, submission_quality_score
from src.submithub import is_submithub_url, submithub_signal_from_methods


class SubmitHubTests(unittest.TestCase):
    def test_detects_submithub_urls(self):
        self.assertTrue(is_submithub_url("https://www.submithub.com/blog/playlist-name"))
        self.assertTrue(is_submithub_url("https://curator.submithub.com/profile"))
        self.assertFalse(is_submithub_url("https://example.com/submithub"))

    def test_extracts_signal_from_contact_methods(self):
        signal = submithub_signal_from_methods(
            [{"type": "submission_page", "value": "https://www.submithub.com/to/curator", "confidence_score": 86}]
        )

        self.assertTrue(signal["submithub_verified"])
        self.assertEqual(signal["submithub_confidence"], 86)

    def test_submithub_improves_contact_and_score_breakdown(self):
        contact = {
            "submission_page": "https://www.submithub.com/to/curator",
            "submithub_verified": True,
            "submithub_confidence": 90,
            "confidence_score": 70,
        }

        self.assertEqual(submission_quality_score(contact), 95)
        self.assertGreaterEqual(contactability_score(contact), 90)
        scored = score_playlist(70, 5000, contact=contact, intersection_score=20)
        self.assertEqual(scored["breakdown"]["submission_quality"], 95)


if __name__ == "__main__":
    unittest.main()
