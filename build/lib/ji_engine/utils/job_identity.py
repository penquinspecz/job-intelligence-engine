from __future__ import annotations

import hashlib
import json
from typing import Dict
from urllib.parse import urlsplit, urlunsplit


def job_identity(job: Dict[str, object]) -> str:
    """
    Stable identifier for job postings.

    Preference:
    1. job_id
    2. apply_url
    3. detail_url
    4. content hash (title/location/team/description)
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

    job_id = job.get("job_id")
    if isinstance(job_id, str):
        normalized = _normalize(job_id, lower=True)
        if normalized:
            return normalized

    for field in ("apply_url", "detail_url"):
        value = job.get(field)
        if isinstance(value, str):
            normalized = _normalize_url(value)
            if normalized:
                return normalized

    description = (
        job.get("description_text") or job.get("jd_text") or job.get("description") or job.get("descriptionHtml") or ""
    )
    payload = {
        "title": _normalize(str(job.get("title") or ""), lower=True),
        "location": _normalize(str(job.get("location") or job.get("locationName") or ""), lower=True),
        "team": _normalize(str(job.get("team") or job.get("department") or ""), lower=True),
        "description": _normalize(str(description), lower=True),
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
