import tempfile
import unittest
from pathlib import Path

from src.database import (
    add_outreach_event,
    get_all_playlists,
    get_email_queue,
    get_or_create_curator,
    get_song_fit_targets,
    init_db,
    queue_email,
    save_song_fit_targets,
    update_email_queue_status,
    update_playlist_status,
    upsert_playlist,
)


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tmp.name) / "streambase.sqlite")
        init_db(self.db_path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_playlist_and_song_fit_target_persist(self):
        playlist_id = upsert_playlist(
            {
                "curator": "Test Curator",
                "name": "Indie Dance Evergreen",
                "url": "https://open.spotify.com/playlist/evergreen",
                "followers": 2000,
                "related_artists": "MGMT",
                "spotify_description": "indie dance favorites",
                "final_score": 72,
            },
            self.db_path,
        )
        self.assertGreater(playlist_id, 0)
        self.assertEqual(len(get_all_playlists(self.db_path)), 1)

        saved = save_song_fit_targets(
            {"title": "Test Song", "artist": "Test Artist"},
            [
                {
                    "playlist_name": "Indie Dance Evergreen",
                    "playlist_url": "https://open.spotify.com/playlist/evergreen",
                    "curator_name": "Test Curator",
                    "fit_score": 80,
                }
            ],
            self.db_path,
        )

        self.assertEqual(saved, 1)
        self.assertEqual(len(get_song_fit_targets(self.db_path)), 1)

    def test_email_queue_status_flow(self):
        curator_id = get_or_create_curator("Test Curator", self.db_path)
        playlist_id = upsert_playlist(
            {
                "curator": "Test Curator",
                "name": "Playlist",
                "url": "https://open.spotify.com/playlist/abc",
            },
            self.db_path,
        )
        queue_id = queue_email(curator_id, playlist_id, "test@example.com", "Subject", "Body", self.db_path)

        self.assertGreater(queue_id, 0)
        self.assertEqual(get_email_queue("pending_approval", self.db_path)[0]["id"], queue_id)

        update_email_queue_status(queue_id, "approved", self.db_path)
        self.assertEqual(get_email_queue("approved", self.db_path)[0]["id"], queue_id)

        add_outreach_event(curator_id, playlist_id, "email", "sent", "Body", self.db_path)
        update_playlist_status(playlist_id, "sent", self.db_path)
        self.assertEqual(get_all_playlists(self.db_path)[0]["status"], "sent")


if __name__ == "__main__":
    unittest.main()
