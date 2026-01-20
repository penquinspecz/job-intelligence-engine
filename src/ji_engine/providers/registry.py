from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List


def load_providers_config(path: Path) -> List[Dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("providers config must be a list")
    providers: List[Dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            raise ValueError("provider entry must be a dict")
        provider_id = item.get("provider_id")
        careers_url = item.get("careers_url")
        snapshot_path = item.get("snapshot_path")
        mode = (item.get("mode") or "snapshot").lower()
        if not provider_id or not careers_url or not snapshot_path:
            raise ValueError("provider entry missing required fields")
        providers.append(
            {
                "provider_id": str(provider_id),
                "careers_url": str(careers_url),
                "mode": mode,
                "snapshot_path": str(snapshot_path),
            }
        )
    return providers
