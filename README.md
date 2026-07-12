# Streambase CRM v1

Local-first playlist intelligence and outreach CRM for independent artists.

## Adds
- Curator profiles
- Playlist records attached to curators
- Contact method stack: email, Instagram, website, submission page, Linktree/Beacons/Carrd
- Outreach history events
- Priority scoring
- Spotify API playlist metadata and track/artist connector
- Chartmetric connector architecture
- Playlist intersection scoring across reference artists, track artists, and saved playlist overlap
- Song upload fit analysis for playlist lane recommendations
- Spotify track-link Song Fit analysis
- Release-age filtering that avoids new-release playlists for older songs
- Song Fit discovery searches and saved outreach targets
- Spotify playlist search from Song Fit discovery queries
- Email approval queue before send logging
- Outreach drafts
- CSV export
- Local-first SQLite database in `local_data/`

## Run
```bash
cd streambase-crm
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

## Optional connectors

Spotify API enrichment is enabled when both variables are present:

```bash
export SPOTIFY_CLIENT_ID="..."
export SPOTIFY_CLIENT_SECRET="..."
```

Or create a local `.env` file, which is ignored by git:

```bash
cp .env.example .env
```

Then edit `.env`:

```bash
SPOTIFY_CLIENT_ID=...
SPOTIFY_CLIENT_SECRET=...
```

Test the connection:

```bash
python3 scripts/test_spotify.py
```

Chartmetric is scaffolded behind an environment-driven connector. Chartmetric issues a long-lived refresh token, which Streambase exchanges for short-lived access tokens automatically:

```bash
export CHARTMETRIC_REFRESH_TOKEN="..."
export CHARTMETRIC_API_BASE_URL="https://api.chartmetric.com/api"
```

Viberate can run in the parallel Playlist Miner lane with the temporary trial key. The miner defaults to the trial-safe limit of 3 requests/minute:

```bash
export VIBERATE_API_KEY="..."
export VIBERATE_API_BASE_URL="https://data.viberate.com/api/v1"
export VIBERATE_REQUESTS_PER_MINUTE=3
```

Test the Viberate connection:

```bash
python3 scripts/test_viberate.py
```

Email drafts are queued as `pending_approval` records in SQLite. Approve, reject, or mark them sent from the Email Queue tab.

## Song Fit

The Song Fit tab accepts Spotify track links plus WAV, MP3, M4A, AIFF, and FLAC uploads. With Spotify credentials, track links pull title, artists, album, popularity, duration, and artist genres. Without credentials, Streambase falls back to Spotify oEmbed metadata. WAV files also get basic local duration and energy estimates; all formats use title, artist, reference artists, descriptors, and saved CRM playlist context to recommend playlist lanes and matching saved playlists.

Song Fit can save matching CRM playlists as outreach targets and generates discovery search queries for finding new playlist curators.

When Spotify metadata includes a release date, Streambase marks songs older than one year as older catalog and excludes playlists or lanes explicitly focused on new releases, fresh drops, New Music Friday, or similar current-release contexts.

With Spotify credentials connected, Song Fit can search Spotify for playlist candidates from the generated discovery queries, de-duplicate against the CRM, score candidate fit, stage candidates in the import queue, or analyze and save them directly into the CRM.

## Local data safety

Private data is written to `local_data/` by default and ignored by git:

- SQLite CRM database
- imported playlist snapshots
- generated analysis reports
- CSV exports

Keep `data/band_references.json` in git as shared reference data. Do not commit real curator emails, outreach history, reports, or exports.

To store private data somewhere else:

```bash
export STREAMBASE_DATA_DIR="/path/to/private/streambase-data"
```

## Repository shape

The app should live in the repo as normal source files, not as a nested zip. Commit the project files directly and let `.gitignore` keep private working data out of GitHub.

## Direct GitHub upload without local git

If Apple command line tools are not installed, you can upload the clean source tree through the GitHub API:

```bash
export GITHUB_TOKEN="..."
python3 scripts/upload_to_github.py
```

Optional overrides:

```bash
export GITHUB_OWNER="ntsadler"
export GITHUB_REPO="streambase"
export GITHUB_BRANCH="main"
```

The uploader excludes `local_data/`, SQLite databases, reports, raw imports, zips, caches, and virtualenv files.
