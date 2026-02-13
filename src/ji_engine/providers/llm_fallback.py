"""
SignalCraft
Copyright (c) 2026 Chris Menendez.
All Rights Reserved.
See LICENSE for permitted use.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import List

from ji_engine.models import JobSource, RawJobPosting
from ji_engine.utils.job_identity import job_identity


def load_cached_llm_fallback(
    html: str,
    *,
    provider_id: str,
    cache_dir: Path,
    now: datetime,
) -> List[RawJobPosting]:
    digest = hashlib.sha256(html.encode("utf-8")).hexdigest()
    cache_path = cache_dir / provider_id / f"{digest}.json"
    if not cache_path.exists():
        raise RuntimeError(f"LLM fallback cache missing for {provider_id} (hash={digest})")

    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"LLM fallback cache invalid JSON for {provider_id}: {exc}") from exc
    if not isinstance(payload, list):
        raise RuntimeError("LLM fallback cache must be a list of job dicts")

    postings: List[RawJobPosting] = []
    for item in payload:
        if not isinstance(item, dict):
            raise RuntimeError("LLM fallback cache entries must be dicts")
        title = str(item.get("title") or "").strip()
        apply_url = str(item.get("apply_url") or item.get("detail_url") or "").strip()
        if not title or not apply_url:
            raise RuntimeError("LLM fallback cache entries require title and apply_url")
        location = str(item.get("location") or "").strip() or None
        team = str(item.get("team") or "").strip() or None
        identity_seed = {
            "title": title,
            "location": location,
            "team": team,
            "apply_url": apply_url,
        }
        postings.append(
            RawJobPosting(
                source=JobSource.ASHBY,
                title=title,
                location=location,
                team=team,
                apply_url=apply_url,
                detail_url=str(item.get("detail_url") or apply_url),
                raw_text=str(item.get("raw_text") or ""),
                scraped_at=now,
                job_id=job_identity(identity_seed, mode="provider"),
            )
        )
    postings.sort(key=lambda item: ((item.apply_url or "").lower(), (item.title or "").lower()))
    return postings
