import unittest

from src.gmail_replies import _match_reply


class GmailRepliesTests(unittest.TestCase):
    def test_match_reply_by_sender_and_subject(self):
        sent_rows = [
            {
                "id": 7,
                "curator_id": 3,
                "playlist_id": 11,
                "to_email": "curator@example.com",
                "subject": "Submission for Night Drive",
            }
        ]

        match = _match_reply(
            {
                "from_email": "curator@example.com",
                "subject": "Re: Submission for Night Drive",
            },
            sent_rows,
        )

        self.assertEqual(match["match_status"], "matched_subject")
        self.assertEqual(match["email_queue_id"], 7)
        self.assertEqual(match["playlist_id"], 11)

    def test_match_reply_falls_back_to_sender(self):
        sent_rows = [
            {
                "id": 9,
                "curator_id": 4,
                "playlist_id": 12,
                "to_email": "curator@example.com",
                "subject": "Submission for Other Playlist",
            }
        ]

        match = _match_reply(
            {
                "from_email": "curator@example.com",
                "subject": "Different subject",
            },
            sent_rows,
        )

        self.assertEqual(match["match_status"], "matched_sender")
        self.assertEqual(match["email_queue_id"], 9)


if __name__ == "__main__":
    unittest.main()
