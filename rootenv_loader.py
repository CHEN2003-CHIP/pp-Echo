from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


def find_env_file() -> Path | None:
    """Find the nearest .env file if the workspace provides one."""

    current = Path(__file__).resolve().parent
    for _ in range(10):
        candidate = current / ".env"
        if candidate.exists():
            return candidate
        current = current.parent
    return None


_ENV_FILE = find_env_file()
if _ENV_FILE is not None:
    load_dotenv(_ENV_FILE, override=True)


def env(key, default=None):
    """Read an environment variable after optional .env loading."""

    return os.getenv(key, default)
