import unittest

from src.playlist_discovery import artist_playlist_searches, discover_catalog_song_playlists, discover_released_track_playlists
from src.song_analyzer import analyze_song_fit, preferred_catalog_title, score_spotify_playlist_candidates, suggest_reference_song_searches


class SongAnalyzerTests(unittest.TestCase):
    def test_released_song_prefers_spotify_title_over_uploaded_file(self):
        title = preferred_catalog_title(
            "rough_mix_v7",
            "rough_mix_v7",
            {"title": "Hideout In The District"},
            "released",
        )
        self.assertEqual(title, "Hideout In The District")

    def test_unreleased_song_keeps_analysis_title(self):
        title = preferred_catalog_title(
            "rough_mix_v7",
            "Cyanite Upload Title",
            {"title": "Spotify Title"},
            "unreleased",
        )
        self.assertEqual(title, "Cyanite Upload Title")

    def test_song_fit_recommends_matching_lane_from_spotify_metadata(self):
        meta = {
            "title": "Night Drive",
            "artist": "Test Artist",
            "reference_artists": "MGMT; LCD Soundsystem",
            "descriptors": "indie dance; electronic; synth",
            "release_date": "2026-05-01",
            "duration_ms": 210000,
            "popularity": 30,
        }
        result = analyze_song_fit(None, saved_playlists=[], spotify_track=meta)

        self.assertEqual(result["recommended_playlist_lanes"][0]["lane"], "Indie electronic / alt dance")
        self.assertFalse(result["release_guidance"]["exclude_new_release_playlists"])

    def test_old_song_excludes_new_release_playlists(self):
        meta = {
            "title": "Old Song",
            "artist": "Test Artist",
            "reference_artists": "MGMT; LCD Soundsystem",
            "descriptors": "indie dance; electronic",
            "release_date": "2024-01-01",
            "duration_ms": 210000,
            "popularity": 35,
        }
        playlists = [
            {
                "name": "New Music Friday Indie",
                "curator_name": "A",
                "url": "https://open.spotify.com/playlist/new",
                "related_artists": "MGMT",
                "spotify_description": "new releases fresh drops",
                "final_score": 90,
            },
            {
                "name": "Indie Dance Classics",
                "curator_name": "B",
                "url": "https://open.spotify.com/playlist/evergreen",
                "related_artists": "MGMT",
                "spotify_description": "indie dance electronic favorites",
                "final_score": 80,
            },
        ]

        result = analyze_song_fit(None, saved_playlists=playlists, spotify_track=meta)

        self.assertTrue(result["release_guidance"]["exclude_new_release_playlists"])
        self.assertEqual([m["playlist_name"] for m in result["saved_playlist_matches"]], ["Indie Dance Classics"])
        self.assertTrue(all("evergreen" in s["search_query"] for s in result["discovery_searches"]))
        self.assertTrue(all("curator" not in s["search_query"].lower() for s in result["discovery_searches"]))
        self.assertTrue(any("submission" in s["search_query"].lower() for s in result["discovery_searches"]))

    def test_no_release_date_does_not_exclude_new_release_context(self):
        meta = {
            "title": "Unknown Date Song",
            "artist": "Test Artist",
            "reference_artists": "MGMT",
            "descriptors": "fresh indie electronic",
        }
        result = analyze_song_fit(None, saved_playlists=[], spotify_track=meta)

        self.assertEqual(result["release_guidance"]["release_age_label"], "unknown")
        self.assertFalse(result["release_guidance"]["exclude_new_release_playlists"])

    def test_new_release_context_is_allowed_without_spotify_url(self):
        meta = {
            "title": "Unreleased Song",
            "artist": "Test Artist",
            "release_context": "new_release",
            "descriptors": "indie dance; energetic",
        }

        result = analyze_song_fit(None, saved_playlists=[], spotify_track=meta)

        self.assertEqual(result["release_guidance"]["release_age_label"], "new release")
        self.assertFalse(result["release_guidance"]["exclude_new_release_playlists"])

    def test_candidate_scoring_dedupes_and_filters_new_release_for_old_song(self):
        meta = {
            "title": "Old Song",
            "artist": "Test Artist",
            "reference_artists": "MGMT; LCD Soundsystem",
            "descriptors": "indie dance; electronic",
            "release_date": "2024-01-01",
        }
        fit = analyze_song_fit(None, saved_playlists=[], spotify_track=meta)
        candidates = [
            {
                "playlist_name": "New Music Friday Indie",
                "playlist_url": "https://open.spotify.com/playlist/new",
                "curator_name": "A",
                "follower_count": 5000,
                "related_artists": "MGMT",
                "spotify_description": "new releases fresh drops",
                "search_query": "new music",
            },
            {
                "playlist_name": "Indie Dance Evergreen",
                "playlist_url": "https://open.spotify.com/playlist/evergreen",
                "curator_name": "B",
                "follower_count": 2000,
                "related_artists": "MGMT",
                "spotify_description": "indie dance favorites",
                "search_query": "evergreen indie dance",
            },
        ]
        existing = [{"url": "https://open.spotify.com/playlist/evergreen"}]

        scored = score_spotify_playlist_candidates(fit, candidates, existing)

        self.assertEqual(len(scored), 1)
        self.assertEqual(scored[0]["playlist_name"], "Indie Dance Evergreen")
        self.assertTrue(scored[0]["already_in_crm"])
        self.assertGreater(scored[0]["candidate_fit_score"], 0)

    def test_reference_tracks_feed_lane_and_search_context(self):
        meta = {
            "title": "My Track",
            "artist": "Test Artist",
            "release_date": "2026-05-01",
        }
        reference_tracks = [
            {
                "title": "Reference One",
                "artist": "LCD Soundsystem",
                "reference_artists": "LCD Soundsystem",
                "descriptors": "indie dance; electronic; synth",
                "popularity": 55,
            },
            {
                "title": "Reference Two",
                "artist": "MGMT",
                "reference_artists": "MGMT",
                "descriptors": "indie pop; synth",
                "popularity": 60,
            },
        ]

        result = analyze_song_fit(None, saved_playlists=[], spotify_track=meta, reference_tracks=reference_tracks)

        self.assertEqual(result["recommended_playlist_lanes"][0]["lane"], "Indie electronic / alt dance")
        self.assertIn("MGMT", result["reference_track_summary"]["reference_artists"])
        self.assertTrue(any("indie dance" in s["search_query"] for s in result["discovery_searches"]))
        self.assertFalse(any("MGMT" in s["search_query"] for s in result["discovery_searches"]))

    def test_cyanite_tags_feed_lane_context(self):
        meta = {
            "title": "Soft Track",
            "artist": "Test Artist",
            "release_date": "2026-05-01",
        }
        cyanite = {
            "source": "cyanite",
            "genres": ["bedroom pop"],
            "moods": ["dreamy", "chill"],
            "instruments": ["soft synth"],
            "keywords": [],
            "energy": "low",
            "descriptors": "bedroom pop; dreamy; chill; soft synth",
        }

        result = analyze_song_fit(None, saved_playlists=[], spotify_track=meta, cyanite_profile=cyanite)

        self.assertEqual(result["recommended_playlist_lanes"][0]["lane"], "Bedroom pop / chill indie")
        self.assertIn("bedroom pop", result["song"]["descriptors"])
        self.assertEqual(result["cyanite_summary"]["source"], "cyanite")
        self.assertTrue(any("bedroom pop" in s["search_query"] for s in result["discovery_searches"]))
        self.assertFalse(any("curator" in s["search_query"].lower() for s in result["discovery_searches"]))
        self.assertTrue(any("submission" in s["search_query"].lower() for s in result["discovery_searches"]))

    def test_specific_cyanite_fields_feed_search_and_scoring(self):
        meta = {
            "title": "Guitar Track",
            "artist": "Test Artist",
            "release_date": "2026-05-01",
        }
        cyanite = {
            "source": "cyanite",
            "genres": ["alternative rock"],
            "moods": ["driving"],
            "instruments": ["electric guitar", "live drums"],
            "voice": "male vocal",
            "movement": "angular",
            "energy": "energetic",
        }
        candidates = [
            {
                "playlist_name": "Angular Guitar Discoveries",
                "playlist_url": "https://open.spotify.com/playlist/guitar",
                "curator_name": "Curator",
                "follower_count": 1200,
                "related_artists": "",
                "spotify_description": "alternative rock with electric guitar and live drums",
                "search_query": "alternative rock electric guitar playlist",
            }
        ]

        result = analyze_song_fit(None, saved_playlists=[], spotify_track=meta, cyanite_profile=cyanite)
        scored = score_spotify_playlist_candidates(result, candidates, [])

        self.assertEqual(result["recommended_playlist_lanes"][0]["lane"], "Alternative rock / modern indie")
        self.assertIn("electric guitar", result["cyanite_evidence_terms"])
        self.assertIn("live drums", result["song"]["descriptors"])
        self.assertTrue(any("electric guitar" in s["search_query"] for s in result["discovery_searches"]))
        self.assertIn("electric guitar", scored[0]["matched_descriptors"])

    def test_reference_song_searches_use_descriptors_and_cyanite(self):
        searches = suggest_reference_song_searches(
            {"artist": "Test Artist", "reference_artists": ["Clairo"]},
            "bedroom pop; dreamy",
            {"descriptors": "chill; soft synth"},
            [{"lane": "Bedroom pop / chill indie"}],
        )

        queries = [item["search_query"] for item in searches]
        self.assertTrue(any("Clairo" in query for query in queries))
        self.assertTrue(any("bedroom pop" in query for query in queries))
        self.assertTrue(any("chill" in query for query in queries))

    def test_submission_friendly_discovery_playlist_scores_above_passive_playlist(self):
        meta = {
            "title": "New Track",
            "artist": "Test Artist",
            "reference_artists": "Clairo",
            "descriptors": "bedroom pop; dreamy; chill",
            "release_date": "2026-05-01",
        }
        fit = analyze_song_fit(None, saved_playlists=[], spotify_track=meta)
        candidates = [
            {
                "playlist_name": "Bedroom Pop Emerging Artists",
                "playlist_url": "https://open.spotify.com/playlist/discovery",
                "curator_name": "Indie Blog Curator",
                "follower_count": 2200,
                "related_artists": "Clairo",
                "spotify_description": "Independent artists, submit music for playlist submissions.",
                "search_query": "bedroom pop emerging artists playlist",
            },
            {
                "playlist_name": "Chill Study Hits",
                "playlist_url": "https://open.spotify.com/playlist/study",
                "curator_name": "Passive List",
                "follower_count": 90000,
                "related_artists": "Clairo",
                "spotify_description": "background study focus hits",
                "search_query": "bedroom pop playlist",
            },
        ]

        scored = score_spotify_playlist_candidates(fit, candidates, [])

        self.assertEqual(scored[0]["playlist_name"], "Bedroom Pop Emerging Artists")
        self.assertIn("emerging artists", scored[0]["discovery_intent_hits"])
        self.assertIn("submit music", scored[0]["submission_ready_hits"])
        self.assertIn("study", scored[1]["passive_context_hits"])

    def test_released_track_discovery_adds_artist_playlist_queries(self):
        meta = {
            "title": "Released Track",
            "artist": "Test Artist",
            "reference_artists": "Clairo; Beabadoobee",
            "descriptors": "bedroom pop; indie pop; dreamy",
            "release_date": "2026-01-01",
        }
        fit = analyze_song_fit(None, saved_playlists=[], spotify_track=meta)

        searches = artist_playlist_searches(fit)
        queries = [item["search_query"] for item in searches]

        self.assertTrue(any("Clairo" in query for query in queries))
        self.assertTrue(any("playlist" in query for query in queries))

    def test_discover_released_track_playlists_scores_fake_spotify_results(self):
        meta = {
            "title": "Released Track",
            "artist": "Test Artist",
            "reference_artists": "Clairo",
            "descriptors": "bedroom pop; dreamy; chill",
            "release_date": "2026-01-01",
        }

        def fake_search(queries, limit, markets):
            return {
                "ok": True,
                "error": "",
                "markets": markets,
                "playlists": [
                    {
                        "playlist_name": "Clairo Bedroom Pop",
                        "playlist_url": "https://open.spotify.com/playlist/clairo",
                        "curator_name": "Curator",
                        "follower_count": 2500,
                        "related_artists": "Clairo; Beabadoobee",
                        "spotify_description": "dreamy bedroom pop favorites",
                        "search_query": queries[0],
                    }
                ],
            }

        result = discover_released_track_playlists(
            meta,
            saved_playlists=[],
            query_limit=2,
            limit_per_query=3,
            markets=["US"],
            search_fn=fake_search,
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["queries_run"][0], "Clairo emerging artists playlist")
        self.assertEqual(result["candidates"][0]["playlist_name"], "Clairo Bedroom Pop")
        self.assertGreater(result["candidates"][0]["candidate_fit_score"], 0)

    def test_discover_catalog_song_playlists_uses_saved_cyanite_tags(self):
        song = {
            "id": 42,
            "title": "Catalog Song",
            "artist_name": "Test Artist",
            "release_status": "unreleased",
            "genre_tags": "alternative rock; indie rock",
            "mood_tags": "driving",
            "instrumentation": "electric guitar; live drums",
            "vocal_style": "male vocal",
            "energy": "energetic",
        }

        def fake_search(queries, limit, markets):
            return {
                "ok": True,
                "error": "",
                "markets": markets,
                "playlists": [
                    {
                        "playlist_name": "Guitar Rock Finds",
                        "playlist_url": "https://open.spotify.com/playlist/guitar-rock",
                        "curator_name": "Curator",
                        "follower_count": 1500,
                        "related_artists": "",
                        "spotify_description": "alternative rock with electric guitar and live drums",
                        "search_query": queries[0],
                    }
                ],
            }

        result = discover_catalog_song_playlists(
            song,
            saved_playlists=[],
            query_limit=2,
            limit_per_query=3,
            markets=["US"],
            search_fn=fake_search,
        )

        self.assertTrue(result["ok"])
        self.assertTrue(any("electric guitar" in query for query in result["queries_run"]))
        self.assertTrue(any("emerging artists" in query for query in result["queries_run"]))
        self.assertEqual(result["candidates"][0]["playlist_name"], "Guitar Rock Finds")
        self.assertGreater(result["candidates"][0]["candidate_fit_score"], 0)

    def test_playlist_discovery_filters_throwback_candidates_without_discovery_intent(self):
        meta = {
            "title": "Modern RnB Song",
            "artist": "Test Artist",
            "reference_artists": "SZA",
            "descriptors": "rnb; alternative rnb; smooth",
            "release_date": "2026-01-01",
        }
        fit = analyze_song_fit(None, saved_playlists=[], spotify_track=meta)
        candidates = [
            {
                "playlist_name": "2000s R&B Classics",
                "playlist_url": "https://open.spotify.com/playlist/throwback",
                "curator_name": "Throwback Curator",
                "follower_count": 5000,
                "related_artists": "SZA",
                "spotify_description": "old school nostalgia and 2000s rnb classics",
                "search_query": "rnb playlist",
            },
            {
                "playlist_name": "Alternative R&B Emerging Artists",
                "playlist_url": "https://open.spotify.com/playlist/emerging",
                "curator_name": "Discovery Curator",
                "follower_count": 1200,
                "related_artists": "SZA",
                "spotify_description": "up and coming independent artists in alternative rnb",
                "search_query": "alternative rnb emerging artists playlist",
            },
        ]

        scored = score_spotify_playlist_candidates(fit, candidates, [])

        self.assertEqual([item["playlist_name"] for item in scored], ["Alternative R&B Emerging Artists"])
        self.assertIn("emerging artists", scored[0]["discovery_intent_hits"])


if __name__ == "__main__":
    unittest.main()
