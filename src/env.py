import os
from pathlib import Path


def load_local_env(path: str = ".env") -> None:
    env_path = Path(path)
    if not env_path.is_absolute():
        env_path = Path(__file__).resolve().parents[1] / env_path
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and (key not in os.environ or os.environ.get(key, "") == ""):
            os.environ[key] = value


load_local_env()
