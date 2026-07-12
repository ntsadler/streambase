# Streambase Savepoint

Saved at: 2026-07-09 01:27:25 America/Los_Angeles

## Current State

- Streamlit app: http://127.0.0.1:8501/
- Viberate key is present in `.env`.
- Viberate mining integration is present.
- Chartmetric mining lane remains available for later.
- Song Targets now ranks saved playlist targets together with top mined Viberate/Chartmetric playlist recommendations per selected song.
- Mined playlist rows are recommendation-only in Song Targets until saved as playlist records; enrich/campaign actions only run on saved playlist rows.

## Data Snapshot

- `mined_playlists`: 4,996 Viberate playlist rows.
- `song_playlist_targets`: 494 song-specific seed playlist rows.
- Latest completed Viberate mining jobs:
  - Job 23: completed, 399 saved.
  - Job 22: completed, 329 saved.
  - Job 20: completed, 306 saved.
  - Job 19: completed, 399 saved.
  - Job 18: completed, 379 saved.

## Backup

- SQLite backup: `work/savepoints/streambase-20260709-012725.sqlite`

## Resume Notes

- Open Song Targets and select catalog songs to review ranked playlist matches.
- The `Source` column separates saved playlist rows from `viberate` and `chartmetric` mined recommendations.
- Next useful step: add a button to promote selected mined recommendations into saved playlist records so they can be contact-enriched and added to campaigns.
