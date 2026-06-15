import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.spotify_api import SpotifyAPI, search_spotify_playlists


def main():
    client = SpotifyAPI()
    if not client.configured:
        raise SystemExit("Spotify credentials not found. Add SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET to .env.")

    token = client._fetch_token()
    if not token:
        raise SystemExit("Spotify token request returned no access token.")

    print("Spotify credentials: OK")

    result = search_spotify_playlists(["indie electronic playlist"], limit_per_query=2, market="US")
    if not result.get("ok"):
        raise SystemExit(f"Spotify playlist search failed: {result.get('error')}")

    print(f"Spotify playlist search: OK ({len(result.get('playlists', []))} result(s))")
    for playlist in result.get("playlists", [])[:2]:
        print(f"- {playlist.get('playlist_name')} | {playlist.get('playlist_url')}")


if __name__ == "__main__":
    main()
