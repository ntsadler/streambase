import unittest

from src.pipeline import normalize_song_context


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


if __name__ == "__main__":
    unittest.main()
