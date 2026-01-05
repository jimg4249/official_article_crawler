import json
import logging
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

def log(message: str) -> None:
    logger.info(message)


def get_cache_dir() -> Path:
    cache_dir = Path(__file__).parent.parent / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir

def load_json_file(file_path: Path, default: Any = None) -> Any:
    if not file_path.exists():
        return default

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return default


def save_json_file(file_path: Path, data: Any, ensure_dir: bool = True) -> None:
    if ensure_dir:
        file_path.parent.mkdir(parents=True, exist_ok=True)

    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_json_with_expiry(file_path: Path, default: Any = None) -> tuple[Any, bool]:
    if not file_path.exists():
        return default, True

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        expire_at = data.get("expire_at", 0)
        if expire_at < time.time():
            file_path.unlink()
            return default, True

        return data, False
    except (json.JSONDecodeError, KeyError, OSError):
        return default, True


def save_json_with_expiry(file_path: Path, data: dict, expire_seconds: int) -> None:
    data["expire_at"] = time.time() + expire_seconds
    save_json_file(file_path, data, ensure_dir=True)
