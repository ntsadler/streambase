import tempfile
import unittest
from pathlib import Path

from src.database import (
    add_outreach_event,
    get_all_playlists,
    get_email_queue,
    get_artist_songs,
    get_artist_sound_profile,
    get_release_campaigns,
    get_release_songs,
    get_or_create_curator,
    get_song_fit_targets,
    init_db,
    playlist_outreach_guard,
    queue_email,
    save_song_fit_targets,
    save_artist_sound_profile,
    save_release_campaign_brief,
    backup_song_profiles_json,
    get_artist_references,
    upsert_artist_reference,
    update_email_queue_status,
    update_playlist_status,
    upsert_playlist,
    upsert_artist_song,
    upsert_release_song,
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
                "submithub_verified": True,
                "submithub_url": "https://www.submithub.com/to/test-curator",
            },
            self.db_path,
        )
        self.assertGreater(playlist_id, 0)
        self.assertEqual(len(get_all_playlists(self.db_path)), 1)
        playlist = get_all_playlists(self.db_path)[0]
        self.assertEqual(playlist["submithub_verified"], 1)
        self.assertEqual(playlist["submithub_url"], "https://www.submithub.com/to/test-curator")

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
        queue_id = queue_email(
            curator_id,
            playlist_id,
            "test@example.com",
            "Subject",
            "Body",
            self.db_path,
            song_context={"title": "Test Song", "spotify_url": "https://open.spotify.com/track/test"},
        )

        self.assertGreater(queue_id, 0)
        queued = get_email_queue("pending_approval", self.db_path)[0]
        self.assertEqual(queued["id"], queue_id)
        self.assertEqual(queued["song_title"], "Test Song")
        self.assertEqual(queued["song_url"], "https://open.spotify.com/track/test")

        update_email_queue_status(queue_id, "approved", self.db_path)
        self.assertEqual(get_email_queue("approved", self.db_path)[0]["id"], queue_id)

        add_outreach_event(curator_id, playlist_id, "email", "sent", "Body", self.db_path)
        update_playlist_status(playlist_id, "sent", self.db_path)
        self.assertEqual(get_all_playlists(self.db_path)[0]["status"], "sent")

    def test_playlist_outreach_guard_blocks_back_to_back_song_queue(self):
        curator_id = get_or_create_curator("Test Curator", self.db_path)
        playlist_id = upsert_playlist(
            {
                "curator": "Test Curator",
                "name": "Playlist",
                "url": "https://open.spotify.com/playlist/cooldown",
            },
            self.db_path,
        )
        first = queue_email(
            curator_id,
            playlist_id,
            "test@example.com",
            "Subject",
            "Body",
            self.db_path,
            song_context={"title": "Song One", "spotify_url": "https://open.spotify.com/track/one"},
        )

        guard = playlist_outreach_guard(
            playlist_id,
            {"title": "Song Two", "spotify_url": "https://open.spotify.com/track/two"},
            30,
            self.db_path,
        )
        second = queue_email(
            curator_id,
            playlist_id,
            "test@example.com",
            "Subject",
            "Body",
            self.db_path,
            song_context={"title": "Song Two", "spotify_url": "https://open.spotify.com/track/two"},
        )

        self.assertGreater(first, 0)
        self.assertFalse(guard["allowed"])
        self.assertIn("Song One", guard["reason"])
        self.assertEqual(second, 0)

    def test_artist_song_and_sound_profile_persist(self):
        song_id = upsert_artist_song(
            {
                "title": "Catalog Song",
                "file_path": str(Path(self.tmp.name) / "catalog-song.wav"),
                "bpm": 122,
                "key": "A minor",
                "genre_tags": "indie dance; psych pop",
                "mood_tags": "late-night; euphoric",
                "energy": "high",
                "danceability": 0.75,
                "instrumentation": "synth; guitar",
                "vocal_style": "male vocal",
                "reference_artists": "MGMT; LCD Soundsystem",
                "notes": "Calibration song",
            },
            self.db_path,
        )
        self.assertGreater(song_id, 0)
        self.assertEqual(get_artist_songs(self.db_path)[0]["title"], "Catalog Song")

        profile = {"song_count": 1, "core_genre_tags": ["indie dance"]}
        json_path = Path(self.tmp.name) / "artist_sound_profile.json"
        saved_path = save_artist_sound_profile(profile, db_path=self.db_path, output_path=json_path)

        self.assertEqual(saved_path, str(json_path))
        stored = get_artist_sound_profile(db_path=self.db_path)
        self.assertEqual(stored["profile"]["core_genre_tags"], ["indie dance"])

    def test_release_song_and_campaign_brief_persist(self):
        song_id = upsert_release_song(
            {
                "title": "Unreleased Track",
                "file_path": str(Path(self.tmp.name) / "unreleased-track.wav"),
                "release_status": "unreleased",
                "planned_release_date": "",
                "campaign_status": "needs_profile",
                "genre_tags": "indie dance",
                "mood_tags": "dreamy",
                "reference_artists": "MGMT",
                "recommended_chartmetric_targets": "playlists containing MGMT",
            },
            self.db_path,
        )

        self.assertGreater(song_id, 0)
        self.assertEqual(get_release_songs(self.db_path)[0]["title"], "Unreleased Track")

        save_release_campaign_brief(song_id, {"song_title": "Unreleased Track"}, "campaign_draft", self.db_path)
        campaigns = get_release_campaigns(self.db_path)

        self.assertEqual(campaigns[0]["song_title"], "Unreleased Track")
        self.assertEqual(campaigns[0]["campaign_brief"]["song_title"], "Unreleased Track")

    def test_song_profiles_json_backup(self):
        upsert_release_song(
            {
                "title": "Backup Track",
                "file_name": "backup-track.wav",
                "file_path": str(Path(self.tmp.name) / "backup-track.wav"),
                "release_status": "unreleased",
                "genre_tags": "indie dance",
                "mood_tags": "dreamy",
                "source": "manual",
                "raw_analysis_json": {"source": "manual"},
            },
            self.db_path,
        )
        output_path = Path(self.tmp.name) / "song_profiles.json"

        saved = backup_song_profiles_json(self.db_path, output_path)

        self.assertEqual(saved, str(output_path))
        self.assertIn("Backup Track", output_path.read_text(encoding="utf-8"))
        self.assertIn("backup-track.wav", output_path.read_text(encoding="utf-8"))

    def test_artist_references_track_source_confidence_and_review(self):
        ref_id = upsert_artist_reference(
            {
                "artist_name": "MGMT",
                "source": "chartmetric",
                "confidence_score": 87,
                "approved_by_user": False,
                "rejected_by_user": False,
            },
            self.db_path,
        )
        self.assertGreater(ref_id, 0)

        upsert_artist_reference(
            {
                "artist_name": "LCD Soundsystem",
                "source": "manual",
                "confidence_score": 100,
                "approved_by_user": True,
                "rejected_by_user": False,
            },
            self.db_path,
        )
        upsert_artist_reference(
            {
                "artist_name": "Bad Match",
                "source": "spotify",
                "confidence_score": 90,
                "approved_by_user": False,
                "rejected_by_user": True,
            },
            self.db_path,
        )

        refs = get_artist_references(self.db_path, include_rejected=False)

        self.assertEqual(refs[0]["artist_name"], "LCD Soundsystem")
        self.assertNotIn("Bad Match", [r["artist_name"] for r in refs])


if __name__ == "__main__":
    unittest.main()
