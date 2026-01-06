from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from ji_engine.config import DATA_DIR
from ji_engine.utils.atomic_write import atomic_write_text


class AICache:
    def get(self, job_id: str, content_hash: str) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    def put(self, job_id: str, content_hash: str, payload: Dict[str, Any]) -> None:
        raise NotImplementedError


class FileSystemAICache(AICache):
    def __init__(self, root: Path = DATA_DIR / "ai_cache"):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, job_id: str, content_hash: str) -> Path:
        return self.root / f"{job_id}.{content_hash}.json"

    def get(self, job_id: str, content_hash: str) -> Optional[Dict[str, Any]]:
        path = self._path(job_id, content_hash)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def put(self, job_id: str, content_hash: str, payload: Dict[str, Any]) -> None:
        path = self._path(job_id, content_hash)
        atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2))


# TODO: add S3-backed cache implementation when needed.

