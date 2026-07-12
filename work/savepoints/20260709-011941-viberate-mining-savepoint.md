# Streambase Viberate Mining Savepoint

Saved at: 2026-07-09 01:19:41 America/Los_Angeles

## Current State

- Streamlit app: http://127.0.0.1:8501/
- Viberate key is present in `.env`.
- Viberate mining integration files are present in `src/viberate.py` and `src/viberate_mining.py`.
- Chartmetric mining lane remains available for later.
- The app currently stores Viberate/Chartmetric mined playlists as catalog-wide rows in `mined_playlists`, not per-song rows.

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

- SQLite backup: `work/savepoints/streambase-20260709-011941.sqlite`

## Resume Notes

- To continue mining, use the Viberate mining path and keep the trial-period limit at 3 requests/minute.
- If song-specific mined playlist views are needed later, add a bridge from `mined_playlists` to catalog songs, either with a join table or by scoring mined playlist rows against each song's Cyanite genre, mood, and reference artist profile.
