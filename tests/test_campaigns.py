import unittest

from src.campaigns import DEFAULT_CAMPAIGN_BODY, prepare_campaign_plan, render_campaign_template


class CampaignTests(unittest.TestCase):
    def test_shared_campaign_template_only_changes_playlist_name(self):
        song = {"title": "Same Song", "spotify_url": "https://open.spotify.com/track/shared"}
        first = render_campaign_template(DEFAULT_CAMPAIGN_BODY, "Playlist One", song)
        second = render_campaign_template(DEFAULT_CAMPAIGN_BODY, "Playlist Two", song)

        self.assertIn("Playlist One", first)
        self.assertIn("Playlist Two", second)
        self.assertNotIn("Playlist Two", first)
        self.assertIn(song["spotify_url"], first)
        self.assertIn(song["spotify_url"], second)

    def test_prepare_campaign_picks_best_song_per_playlist(self):
        candidates = [
            {
                "playlist_name": "Indie Finds",
                "playlist_url": "https://open.spotify.com/playlist/one",
                "curator_name": "Curator A",
                "final_score": 72,
                "song_context": {"title": "Lower Fit"},
            },
            {
                "playlist_name": "Indie Finds",
                "playlist_url": "https://open.spotify.com/playlist/one",
                "curator_name": "Curator A",
                "final_score": 91,
                "song_context": {"title": "Best Fit"},
            },
        ]

        plan = prepare_campaign_plan(candidates)

        self.assertEqual(len(plan["rows"]), 1)
        self.assertEqual(plan["rows"][0]["selected_song"], "Best Fit")
        self.assertEqual(plan["rows"][0]["alternates"][0]["song"], "Lower Fit")

    def test_prepare_campaign_holds_duplicate_curator(self):
        candidates = [
            {
                "playlist_name": "Best Playlist",
                "playlist_url": "https://open.spotify.com/playlist/best",
                "curator_name": "Same Curator",
                "final_score": 93,
                "song_context": {"title": "Song A"},
            },
            {
                "playlist_name": "Second Playlist",
                "playlist_url": "https://open.spotify.com/playlist/second",
                "curator_name": "Same Curator",
                "final_score": 80,
                "song_context": {"title": "Song B"},
            },
        ]

        plan = prepare_campaign_plan(candidates)
        statuses = {row["playlist_name"]: row["status"] for row in plan["rows"]}

        self.assertEqual(statuses["Best Playlist"], "Ready")
        self.assertEqual(statuses["Second Playlist"], "Wait")

    def test_prepare_campaign_holds_duplicate_email_route(self):
        candidates = [
            {
                "playlist_name": "Strong Email Fit",
                "playlist_url": "https://open.spotify.com/playlist/strong",
                "curator_name": "Curator A",
                "final_score": 92,
                "email": "submit@example.com",
                "song_context": {"title": "Song A"},
            },
            {
                "playlist_name": "Weaker Email Fit",
                "playlist_url": "https://open.spotify.com/playlist/weaker",
                "curator_name": "Curator B",
                "final_score": 75,
                "email": "SUBMIT@example.com",
                "song_context": {"title": "Song B"},
            },
        ]

        plan = prepare_campaign_plan(candidates)
        rows = {row["playlist_name"]: row for row in plan["rows"]}

        self.assertEqual(rows["Strong Email Fit"]["status"], "Ready")
        self.assertTrue(rows["Strong Email Fit"]["send"])
        self.assertEqual(rows["Weaker Email Fit"]["status"], "Wait")
        self.assertFalse(rows["Weaker Email Fit"]["send"])
        self.assertIn("same email address", rows["Weaker Email Fit"]["reason"])

    def test_prepare_campaign_marks_incredible_recent_fit_worth_considering(self):
        candidates = [
            {
                "playlist_id": 7,
                "playlist_name": "Discovery Playlist",
                "playlist_url": "https://open.spotify.com/playlist/discovery",
                "curator_name": "Curator",
                "final_score": 90,
                "email": "curator@example.com",
                "song_context": {"title": "Strong Fit"},
            },
        ]

        def blocked_guard(playlist_id, song_context, cooldown_days):
            return {"allowed": False, "reason": "Playlist contacted 12 day(s) ago."}

        plan = prepare_campaign_plan(candidates, guard_fn=blocked_guard)

        self.assertEqual(plan["rows"][0]["status"], "Worth considering")
        self.assertTrue(plan["rows"][0]["send"])

    def test_prepare_campaign_recommends_instagram_when_no_submission_link(self):
        candidates = [
            {
                "playlist_name": "Indie Discovery",
                "playlist_url": "https://open.spotify.com/playlist/discovery",
                "curator_name": "Curator",
                "final_score": 74,
                "instagram": "https://instagram.com/curator",
                "song_context": {"title": "Song"},
                "discovery_intent_hits": ["emerging artists"],
                "submission_ready_hits": ["submit music"],
            },
        ]

        plan = prepare_campaign_plan(candidates)

        self.assertEqual(plan["rows"][0]["recommended_channel"], "Instagram")
        self.assertIn("Submission-friendly language", plan["rows"][0]["reason"])

    def test_prepare_campaign_regenerates_copy_without_song_or_curator_name(self):
        candidates = [
            {
                "playlist_name": "Indie Finds",
                "playlist_url": "https://open.spotify.com/playlist/one",
                "curator_name": "Alex",
                "final_score": 80,
                "email_message": "Old draft with Song Title and Alex",
                "song_context": {
                    "title": "Song Title",
                    "artist": "Nick Sadler",
                    "spotify_url": "https://open.spotify.com/track/abc123",
                    "release_status": "released",
                },
            },
        ]

        plan = prepare_campaign_plan(candidates)
        row = plan["rows"][0]

        self.assertIn("https://open.spotify.com/track/abc123", row["email_message"])
        self.assertIn("https://open.spotify.com/track/abc123", row["instagram_dm"])
        self.assertNotIn("Song Title", row["email_message"])
        self.assertNotIn("Alex", row["instagram_dm"])

    def test_prepare_campaign_uses_direct_song_url_fallback_in_copy(self):
        candidates = [
            {
                "playlist_name": "Indie Finds",
                "playlist_url": "https://open.spotify.com/playlist/one",
                "curator_name": "Alex",
                "final_score": 80,
                "song_url": "https://open.spotify.com/track/fallback",
                "song_context": {"title": "Song Title", "release_status": "released"},
            },
        ]

        plan = prepare_campaign_plan(candidates)
        row = plan["rows"][0]

        self.assertIn("https://open.spotify.com/track/fallback", row["email_message"])
        self.assertIn("https://open.spotify.com/track/fallback", row["instagram_dm"])


if __name__ == "__main__":
    unittest.main()
