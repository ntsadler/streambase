import unittest

from src.outreach_generator import generate_outreach


class OutreachGeneratorTests(unittest.TestCase):
    def test_released_song_copy_includes_spotify_url(self):
        messages = generate_outreach(
            {"playlist_name": "Indie Dance Finds", "curator_name": "Alex"},
            {"breakdown": []},
            {
                "title": "Night Drive",
                "artist": "Nick Sadler",
                "spotify_url": "https://open.spotify.com/track/abc123",
                "release_status": "released",
            },
        )

        for key in ["email_message", "instagram_dm", "submission_note", "follow_up_message"]:
            self.assertIn("https://open.spotify.com/track/abc123", messages[key])
            self.assertIn("Night Drive", messages[key])

    def test_unreleased_song_copy_uses_preview_url_when_available(self):
        messages = generate_outreach(
            {"playlist_name": "Indie Dance Finds", "curator_name": "Alex"},
            {"breakdown": []},
            {
                "title": "Unreleased Track",
                "artist": "Nick Sadler",
                "preview_url": "https://soundcloud.com/private-link",
                "release_status": "unreleased",
            },
        )

        self.assertIn("https://soundcloud.com/private-link", messages["email_message"])
        self.assertNotIn("open.spotify.com", messages["email_message"])


if __name__ == "__main__":
    unittest.main()

