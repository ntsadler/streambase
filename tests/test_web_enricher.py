import unittest
from unittest.mock import Mock

from src.web_enricher import valid_contact_email
from src.tavily_enricher import enrich_playlist_with_tavily


class WebEnricherTests(unittest.TestCase):
    def test_rejects_duckduckgo_error_email(self):
        self.assertFalse(valid_contact_email("error-lite@duckduckgo.com", "duckduckgo_search"))

    def test_rejects_search_provider_domains(self):
        self.assertFalse(valid_contact_email("support@google.com", "duckduckgo_search"))

    def test_accepts_normal_curator_email(self):
        self.assertTrue(valid_contact_email("submissions@indiecurator.com", "https://indiecurator.com/contact"))

    def test_tavily_extracts_matching_playlist_contacts(self):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "results": [
                {
                    "title": "French Poolside Disco submissions",
                    "url": "https://poolside.example/contact",
                    "content": "French Poolside Disco by Hausers. Email poolside@indiecurator.com or visit https://instagram.com/poolsidecurator and https://amzn.to/unrelated",
                    "raw_content": "Submit at https://poolside.example/submit-music",
                    "score": 0.91,
                }
            ],
            "usage": {"credits": 1},
        }

        result = enrich_playlist_with_tavily(
            {
                "playlist_name": "French Poolside Disco",
                "curator_name": "Hausers",
                "playlist_url": "https://open.spotify.com/playlist/123",
            },
            api_key="tvly-test",
            post=Mock(return_value=response),
        )

        self.assertTrue(result["ok"])
        values = {(item["type"], item["value"]) for item in result["contact_methods"]}
        self.assertIn(("email", "poolside@indiecurator.com"), values)
        self.assertIn(("instagram", "https://instagram.com/poolsidecurator"), values)
        self.assertIn(("submission_page", "https://poolside.example/submit-music"), values)
        self.assertNotIn(("website", "https://amzn.to/unrelated"), values)

    def test_tavily_rejects_unrelated_search_result(self):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "results": [
                {
                    "title": "Generic playlist promotion service",
                    "url": "https://unrelated.example",
                    "content": "Email sales@unrelated.example",
                    "score": 0.95,
                }
            ]
        }
        result = enrich_playlist_with_tavily(
            {"playlist_name": "Tiny Midnight Playlist", "curator_name": "Nick"},
            api_key="tvly-test",
            post=Mock(return_value=response),
        )
        self.assertEqual([], result["contact_methods"])


if __name__ == "__main__":
    unittest.main()
