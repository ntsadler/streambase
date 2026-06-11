import os
from pathlib import Path


LOCAL_DATA_DIR = Path(os.getenv("STREAMBASE_DATA_DIR", "local_data"))
DB_PATH = str(LOCAL_DATA_DIR / "streambase.sqlite")


def local_data_path(name: str) -> Path:
    LOCAL_DATA_DIR.mkdir(parents=True, exist_ok=True)
    return LOCAL_DATA_DIR / name
