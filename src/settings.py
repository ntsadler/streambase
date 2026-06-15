import os
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]


def load_local_env(path=None):
    env_path = Path(path) if path else ROOT_DIR / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#") or "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


load_local_env()

LOCAL_DATA_DIR = Path(os.getenv("STREAMBASE_DATA_DIR", "local_data"))
DB_PATH = str(LOCAL_DATA_DIR / "streambase.sqlite")


def local_data_path(name: str) -> Path:
    LOCAL_DATA_DIR.mkdir(parents=True, exist_ok=True)
    return LOCAL_DATA_DIR / name


def project_data_path(name: str) -> Path:
    path = ROOT_DIR / "data"
    path.mkdir(parents=True, exist_ok=True)
    return path / name
