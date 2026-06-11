import base64
import getpass
import json
import os
import ssl
import subprocess
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen


OWNER = os.getenv("GITHUB_OWNER", "ntsadler")
REPO = os.getenv("GITHUB_REPO", "streambase")
BRANCH = os.getenv("GITHUB_BRANCH", "main")
TOKEN = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
ROOT = Path(__file__).resolve().parents[1]
SSL_CONTEXT = None

try:
    import certifi

    SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    SSL_CONTEXT = ssl.create_default_context()

EXCLUDED_DIRS = {".git", ".venv", "__pycache__", "local_data"}
EXCLUDED_SUFFIXES = {".pyc", ".zip", ".sqlite"}
EXCLUDED_PATHS = {"data/report.json", "data/playlists_raw.json"}


def api(path, method="GET", payload=None):
    if not TOKEN:
        raise SystemExit("Set GITHUB_TOKEN or GH_TOKEN before running this uploader.")
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = Request(
        f"https://api.github.com/repos/{OWNER}/{REPO}{path}",
        data=data,
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {TOKEN}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urlopen(req, timeout=30, context=SSL_CONTEXT) as response:
            body = response.read().decode("utf-8")
            return json.loads(body) if body else {}
    except HTTPError as exc:
        detail = exc.read().decode("utf-8")
        raise SystemExit(f"GitHub API error {exc.code}: {detail}") from exc


def normalize_token(token):
    token = (token or "").strip().strip('"').strip("'")
    marker = "github_pat"
    if marker in token and not token.startswith(marker):
        token = token[token.index(marker):]
    return token


def token_from_clipboard():
    try:
        result = subprocess.run(["pbpaste"], capture_output=True, text=True, timeout=3)
    except (OSError, subprocess.SubprocessError):
        return ""
    token = normalize_token(result.stdout)
    return token if token.startswith("github_pat") else ""


def should_include(path):
    rel = path.relative_to(ROOT).as_posix()
    if rel in EXCLUDED_PATHS:
        return False
    if any(part in EXCLUDED_DIRS for part in path.relative_to(ROOT).parts):
        return False
    if path.suffix in EXCLUDED_SUFFIXES:
        return False
    return path.is_file()


def source_files():
    return sorted(path for path in ROOT.rglob("*") if should_include(path))


def create_blob(path):
    content = base64.b64encode(path.read_bytes()).decode("ascii")
    blob = api("/git/blobs", "POST", {"content": content, "encoding": "base64"})
    return blob["sha"]


def main():
    global TOKEN
    TOKEN = normalize_token(TOKEN)
    if not TOKEN:
        TOKEN = token_from_clipboard()
    if not TOKEN:
        TOKEN = normalize_token(getpass.getpass("GitHub token: "))
    if not TOKEN.startswith("github_pat"):
        raise SystemExit("Token should start with github_pat. Create a fine-grained GitHub token and try again.")
    ref = api(f"/git/ref/heads/{BRANCH}")
    parent_sha = ref["object"]["sha"]
    entries = []
    for path in source_files():
        rel = path.relative_to(ROOT).as_posix()
        entries.append(
            {
                "path": rel,
                "mode": "100644",
                "type": "blob",
                "sha": create_blob(path),
            }
        )
    tree = api("/git/trees", "POST", {"tree": entries})
    commit = api(
        "/git/commits",
        "POST",
        {
            "message": "Upload clean Streambase source tree",
            "tree": tree["sha"],
            "parents": [parent_sha],
        },
    )
    api(f"/git/refs/heads/{BRANCH}", "PATCH", {"sha": commit["sha"], "force": False})
    print(f"Uploaded {len(entries)} files to https://github.com/{OWNER}/{REPO}/tree/{BRANCH}")


if __name__ == "__main__":
    main()
