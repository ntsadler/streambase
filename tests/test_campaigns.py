import unittest

from src.campaigns import prepare_campaign_plan


class CampaignTests(unittest.TestCase):
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

    def test_prepare_campaign_marks_incredible_recent_fit_worth_considering(self):
        candidates = [
            {
                "playlist_id": 7,
                "playlist_name": "Discovery Playlist",
                "playlist_url": "https://open.spotify.com/playlist/discovery",
                "curator_name": "Curator",
                "final_score": 90,
                "song_context": {"title": "Strong Fit"},
            },
        ]

        def blocked_guard(playlist_id, song_context, cooldown_days):
            return {"allowed": False, "reason": "Playlist contacted 12 day(s) ago."}

        plan = prepare_campaign_plan(candidates, guard_fn=blocked_guard)

        self.assertEqual(plan["rows"][0]["status"], "Worth considering")
        self.assertTrue(plan["rows"][0]["send"])


if __name__ == "__main__":
    unittest.main()
