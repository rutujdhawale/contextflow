"""Small .env loader for local demo workflows.

This keeps setup dependency-free while allowing users to place API keys in
ContextFlow/.env for local runs.
"""

from __future__ import annotations

import os
from pathlib import Path

_LOADED = False


def load_dotenv(path: Path | None = None) -> None:
    """Load KEY=VALUE pairs from a .env file into process environment.

    Existing environment variables are preserved and not overwritten.
    """
    global _LOADED
    if _LOADED:
        return
    dotenv_path = path or (Path(__file__).resolve().parents[1] / ".env")
    if not dotenv_path.exists():
        _LOADED = True
        return
    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        value = value.strip().strip("'").strip('"')
        os.environ.setdefault(key, value)
    _LOADED = True

