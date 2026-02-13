"""
SignalCraft
Copyright (c) 2026 Chris Menendez.
All Rights Reserved.
See LICENSE for permitted use.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional


def load_dotenv(path: Optional[str] = None, override: bool = False) -> Dict[str, str]:
    """
    Minimal .env loader:
      - Supports KEY=VALUE lines
      - Ignores blank lines and comments starting with '#'
      - Strips surrounding single/double quotes in VALUE
      - By default does NOT override existing environment variables
    Returns dict of loaded key/values.
    """
    import os

    env_path = Path(path) if path else Path(".env")
    if not env_path.exists():
        return {}

    loaded: Dict[str, str] = {}
    try:
        content = env_path.read_text(encoding="utf-8")
    except (PermissionError, OSError):
        # .env exists but not readable (sandboxed env, permissions, etc.)
        return {}

    for raw in content.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue

        k, v = line.split("=", 1)
        key = k.strip()
        val = v.strip()

        # remove surrounding quotes
        if len(val) >= 2 and ((val[0] == val[-1]) and val[0] in ("'", '"')):
            val = val[1:-1]

        if not key:
            continue

        if override or (key not in os.environ):
            os.environ[key] = val

        loaded[key] = val

    return loaded
