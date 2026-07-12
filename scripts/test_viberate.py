import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.viberate import ViberateAPI


def main():
    client = ViberateAPI()
    if not client.configured:
        raise SystemExit("Viberate key not found. Add VIBERATE_API_KEY to .env.")

    print("Viberate credentials: found")
    print(f"Base URL: {client.base_url}")
    print("Trial throttle: 3 requests/minute by default in the Streambase miner")

    try:
        result = client.search_playlists("indie dance playlist", limit=1)
    except Exception as exc:
        raise SystemExit(f"Viberate playlist search failed: {exc}")

    print(f"Viberate playlist search: OK ({type(result).__name__} response)")


if __name__ == "__main__":
    main()
