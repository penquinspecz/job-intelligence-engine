from __future__ import annotations

from typing import Dict


def job_identity(job: Dict[str, object]) -> str:
    """
    Stable identifier for job postings.

    Preference:
    1. apply_url
    2. detail_url
    3. title + location (or locationName)
    4. empty string
    """
    for field in ("apply_url", "detail_url"):
        value = job.get(field)
        if isinstance(value, str):
            stripped = value.strip()
            if stripped:
                return stripped

    title = str(job.get("title") or "").strip()
    location = str(job.get("location") or job.get("locationName") or "").strip()
    if title or location:
        return f"{title}|{location}"

    return ""
