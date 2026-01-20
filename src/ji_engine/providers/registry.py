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
        provider_type = (item.get("type") or "openai").lower()
        careers_url = item.get("careers_url") or item.get("board_url")
        snapshot_path = item.get("snapshot_path")
        snapshot_dir = item.get("snapshot_dir")
        mode = (item.get("mode") or "snapshot").lower()
        if not provider_id or not careers_url:
            raise ValueError("provider entry missing required fields")
        if not snapshot_path:
            if not snapshot_dir:
                raise ValueError("provider entry missing snapshot_path or snapshot_dir")
            snapshot_path = str(Path(snapshot_dir) / "index.html")
        providers.append(
            {
                "provider_id": str(provider_id),
                "type": provider_type,
                "careers_url": str(careers_url),
                "board_url": str(careers_url),
                "snapshot_dir": str(Path(snapshot_path).parent),
                "mode": mode,
                "snapshot_path": str(snapshot_path),
                "live_enabled": bool(item.get("live_enabled", True)),
            }
        )
    return providers
