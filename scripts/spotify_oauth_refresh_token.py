import http.server
import secrets
import socketserver
import urllib.parse
import webbrowser
from pathlib import Path

import requests


ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"
PORT = 8766
REDIRECT_URI = f"http://127.0.0.1:{PORT}/spotify/callback"
SCOPE = "playlist-read-private playlist-read-collaborative"


def load_env():
    values = {}
    if not ENV_PATH.exists():
        return values
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#") or "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def save_refresh_token(token):
    lines = ENV_PATH.read_text(encoding="utf-8").splitlines() if ENV_PATH.exists() else []
    updated = False
    next_lines = []
    for line in lines:
        if line.startswith("SPOTIFY_REFRESH_TOKEN="):
            next_lines.append(f'SPOTIFY_REFRESH_TOKEN="{token}"')
            updated = True
        else:
            next_lines.append(line)
    if not updated:
        next_lines.append(f'SPOTIFY_REFRESH_TOKEN="{token}"')
    ENV_PATH.write_text("\n".join(next_lines) + "\n", encoding="utf-8")


class OAuthHandler(http.server.BaseHTTPRequestHandler):
    server_version = "StreambaseSpotifyOAuth/1.0"

    def log_message(self, fmt, *args):
        return

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        if parsed.path != "/spotify/callback":
            self.send_response(404)
            self.end_headers()
            return
        self.server.oauth_error = query.get("error", [""])[0]
        self.server.oauth_state = query.get("state", [""])[0]
        self.server.oauth_code = query.get("code", [""])[0]
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(
            b"<html><body><h2>Streambase Spotify authorization received.</h2>"
            b"<p>You can close this tab and return to Terminal.</p></body></html>"
        )


def main():
    env = load_env()
    client_id = env.get("SPOTIFY_CLIENT_ID", "")
    client_secret = env.get("SPOTIFY_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        raise SystemExit("Missing SPOTIFY_CLIENT_ID or SPOTIFY_CLIENT_SECRET in .env")

    state = secrets.token_urlsafe(24)
    params = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPE,
        "state": state,
        "show_dialog": "true",
    }
    auth_url = "https://accounts.spotify.com/authorize?" + urllib.parse.urlencode(params)

    with socketserver.TCPServer(("127.0.0.1", PORT), OAuthHandler) as server:
        server.oauth_code = ""
        server.oauth_error = ""
        server.oauth_state = ""
        print("Opening Spotify authorization in your browser...")
        print(f"Redirect URI must be registered in Spotify Dashboard: {REDIRECT_URI}")
        print(f"Scopes: {SCOPE}")
        webbrowser.open(auth_url)
        server.handle_request()

        if server.oauth_error:
            raise SystemExit(f"Spotify returned an OAuth error: {server.oauth_error}")
        if server.oauth_state != state:
            raise SystemExit("OAuth state did not match. Please run the script again.")
        if not server.oauth_code:
            raise SystemExit("No authorization code received. Please run the script again.")

        resp = requests.post(
            "https://accounts.spotify.com/api/token",
            data={
                "code": server.oauth_code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": REDIRECT_URI,
                "grant_type": "authorization_code",
            },
            timeout=20,
        )
        data = resp.json() if resp.content else {}
        if resp.status_code >= 400:
            raise SystemExit(data.get("error_description") or data.get("error") or f"Token exchange failed: HTTP {resp.status_code}")
        refresh_token = data.get("refresh_token", "")
        if not refresh_token:
            raise SystemExit("Spotify did not return a refresh token. Run again and approve the consent screen.")
        save_refresh_token(refresh_token)
        print("Saved SPOTIFY_REFRESH_TOKEN to .env.")
        print("Restart Streambase, then run Spotify playlist tracklist enrichment.")


if __name__ == "__main__":
    main()
