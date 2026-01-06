from __future__ import annotations

import hashlib
import json
from typing import Any, Dict

from ji_engine.ai.cache import FileSystemAICache
from ji_engine.ai.schema import ensure_ai_payload


def _hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def compute_content_hash(job: Dict[str, Any]) -> str:
    title = (job.get("title") or "").strip()
    desc = (job.get("jd_text") or job.get("description") or "").strip()
    loc = (job.get("location") or job.get("locationName") or "").strip()
    payload = "\n".join([title, desc, loc]).encode("utf-8")
    return _hash_bytes(payload)


def load_cached_ai(job_id: str, content_hash: str, cache: FileSystemAICache | None = None) -> Dict[str, Any] | None:
    cache = cache or FileSystemAICache()
    cached = cache.get(job_id, content_hash)
    return ensure_ai_payload(cached) if cached else None


def save_cached_ai(job_id: str, content_hash: str, payload: Dict[str, Any], cache: FileSystemAICache | None = None) -> None:
    cache = cache or FileSystemAICache()
    cache.put(job_id, content_hash, ensure_ai_payload(payload))

