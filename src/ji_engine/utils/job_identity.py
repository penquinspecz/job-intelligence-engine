from __future__ import annotations

import hashlib
import json
from typing import Dict
from urllib.parse import urlsplit, urlunsplit


def job_identity(job: Dict[str, object]) -> str:
    """
    Stable identifier for job postings.

    Preference:
    1. apply_url
    2. detail_url
    3. title + location (or locationName)
    4. empty string
    """
    def _normalize(value: str, *, lower: bool = False) -> str:
        normalized = " ".join(value.split()).strip()
        return normalized.lower() if lower else normalized

    def _normalize_url(value: str) -> str:
        normalized = _normalize(value)
        if not normalized:
            return ""
        parts = urlsplit(normalized)
        scheme = parts.scheme.lower()
        netloc = parts.netloc.lower()
        path = parts.path.rstrip("/")
        return urlunsplit((scheme, netloc, path, "", ""))

    for field in ("apply_url", "detail_url"):
        value = job.get(field)
        if isinstance(value, str):
            normalized = _normalize_url(value)
            if normalized:
                return normalized

    title = _normalize(str(job.get("title") or ""), lower=True)
    location = _normalize(str(job.get("location") or job.get("locationName") or ""), lower=True)
    if title or location:
        return f"{title}|{location}"

    payload = json.dumps(job, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
