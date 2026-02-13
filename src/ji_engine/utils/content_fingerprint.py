"""
SignalCraft
Copyright (c) 2026 Chris Menendez.
All Rights Reserved.
See LICENSE for permitted use.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict


def content_fingerprint(job: Dict[str, Any]) -> str:
    """
    Stable content hash for change detection.

    Included fields (content-bearing, deterministic):
    - title
    - location/locationName
    - team
    - description_text (derived from description_text/jd_text/description/descriptionHtml)

    Excludes scores, timestamps, and run metadata.
    """
    description = (
        job.get("description_text") or job.get("jd_text") or job.get("description") or job.get("descriptionHtml") or ""
    )
    desc_hash = hashlib.sha256(str(description).encode("utf-8")).hexdigest()
    payload = {
        "title": job.get("title"),
        "location": job.get("location") or job.get("locationName"),
        "team": job.get("team"),
        "description_text_hash": desc_hash,
    }
    raw = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()
