import unittest
from unittest.mock import patch

from src.connectors.cyanite import CyaniteConnector
from src.cyanite import CyaniteAPIError, normalize_cyanite_analysis, prepare_audio_for_cyanite, upload_song_audio_to_cyanite


class FakeUpload:
    def __init__(self, name, data):
        self.name = name
        self._data = data

    def getvalue(self):
        return self._data


class CyaniteTests(unittest.TestCase):
    def test_mp3_prepares_without_conversion(self):
        upload = FakeUpload("song.mp3", b"mp3-data")

        result = prepare_audio_for_cyanite(upload)

        self.assertTrue(result["ok"])
        self.assertEqual(result["audio_bytes"], b"mp3-data")
        self.assertFalse(result["converted"])

    def test_non_mp3_or_wav_is_rejected_for_cyanite(self):
        upload = FakeUpload("song.flac", b"flac-data")

        result = prepare_audio_for_cyanite(upload)

        self.assertFalse(result["ok"])
        self.assertIn("MP3", result["error"])

    @patch.dict("os.environ", {"CYANITE_API_KEY": ""}, clear=False)
    def test_upload_reports_missing_key_after_preparing_audio(self):
        upload = FakeUpload("song.mp3", b"mp3-data")

        result = upload_song_audio_to_cyanite(upload, "Song", "spotify-track-id")

        self.assertFalse(result["ok"])
        self.assertTrue(result["prepared"])
        self.assertIn("CYANITE_API_KEY", result["error"])

    @patch.dict("os.environ", {"CYANITE_API_KEY": "test-key"}, clear=False)
    @patch("src.cyanite.CyaniteAPI.upload_mp3_and_create_track", side_effect=CyaniteAPIError("bad upload"))
    def test_upload_returns_api_errors_without_crashing(self, _upload):
        upload = FakeUpload("song.mp3", b"mp3-data")

        result = upload_song_audio_to_cyanite(upload, "Song", "spotify-track-id")

        self.assertFalse(result["ok"])
        self.assertTrue(result["prepared"])
        self.assertEqual(result["error"], "bad upload")

    @patch.dict("os.environ", {"CYANITE_API_KEY": ""}, clear=False)
    def test_connector_placeholder_is_safe_without_key(self):
        connector = CyaniteConnector()

        self.assertFalse(connector.configured)
        self.assertEqual(connector.status()["configured"], "no")
        self.assertEqual(connector.analyze_upload(None)["source"], "manual")

    def test_normalize_finished_cyanite_analysis(self):
        raw = {
            "data": {
                "libraryTrack": {
                    "__typename": "LibraryTrack",
                    "id": "track-1",
                    "title": "Track 07",
                    "audioAnalysisV7": {
                        "__typename": "AudioAnalysisV7Finished",
                        "result": {
                            "advancedGenreTags": ["electronicDance", "pop"],
                            "advancedSubgenreTags": ["synthPop"],
                            "moodAdvancedTags": ["dreamy", "euphoric"],
                            "advancedInstrumentTags": ["synth", "electricGuitar"],
                            "voiceTags": ["male"],
                            "movementTags": ["groovy"],
                            "characterTags": ["energetic"],
                            "bpmRangeAdjusted": 122.4,
                            "valence": 0.7,
                            "arousal": 0.8,
                            "timeSignature": "4/4",
                            "transformerCaption": "Dreamy energetic synth pop track.",
                        },
                    },
                }
            }
        }

        result = normalize_cyanite_analysis(raw)

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "finished")
        self.assertIn("electronic dance", result["genres"])
        self.assertIn("synth pop", result["genres"])
        self.assertIn("dreamy", result["moods"])
        self.assertIn("synth", result["instruments"])
        self.assertEqual(result["energy"], "high")
        self.assertEqual(result["bpm"], 122.4)


if __name__ == "__main__":
    unittest.main()
