from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict


def load_user_state(path: Path) -> Dict[str, Any]:
    """
    Load user state from a JSON file. Returns an empty dict if missing.
    """
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))
