"""
SignalCraft
Copyright (c) 2026 Chris Menendez.
All Rights Reserved.
See LICENSE for permitted use.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List


class SnapshotJsonProvider:
    """
    Loads a list of raw job dicts from a JSON snapshot file.
    """

    def __init__(self, snapshot_path: Path):
        self.snapshot_path = snapshot_path

    def fetch_jobs(self) -> List[Dict[str, Any]]:
        data = json.loads(self.snapshot_path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise ValueError("snapshot JSON must be a list of jobs")
        return data
