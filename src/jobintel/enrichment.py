"""
SignalCraft
Copyright (c) 2026 Chris Menendez.
All Rights Reserved.
See LICENSE for permitted use.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from ji_engine.config import DATA_DIR

_SENIORITY_RULES: List[Tuple[str, str]] = [
    (r"\bdirector\b", "Director"),
    (r"\bmanager\b|\blead\b", "Manager"),
    (r"\bprincipal\b|\bstaff\b", "Staff"),
    (r"\bsenior\b|\bsr\b", "Senior IC"),
]

_REMOTE_RULES: List[Tuple[str, str]] = [
    (r"\bremote\b", "remote"),
    (r"\bhybrid\b", "hybrid"),
    (r"\b(on[-\s]?site|in[-\s]?office)\b", "onsite"),
]

_DOMAIN_TAG_RULES: List[Tuple[str, str]] = [
    (r"\bcustomer success\b|\bcs\b", "cs"),
    (r"\bsolutions?\s+engineer\b|\bsales\s+engineer\b", "sales-eng"),
    (r"\bpublic sector\b|\bgovernment\b|\bgov\b", "gov"),
    (r"\bsecurity\b", "security"),
    (r"\bplatform\b|\binfra\b|\bsre\b", "infra"),
    (r"\bdata\b|\bml\b|\bai\b", "data"),
]

_LEVEL_RE = re.compile(r"\bL(\d)\b", re.IGNORECASE)


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip().lower()


def _job_id(job: Dict[str, Any]) -> str:
    for key in ("job_id", "id"):
        value = job.get(key)
        if value:
            return str(value)
    for key in ("apply_url", "detail_url", "url"):
        value = job.get(key)
        if value:
            return str(value)
    base = {
        "title": job.get("title"),
        "location": job.get("location"),
        "team": job.get("team"),
    }
    digest = hashlib.sha256(json.dumps(base, sort_keys=True).encode("utf-8")).hexdigest()
    return f"hash:{digest}"


def _input_hash(job: Dict[str, Any]) -> str:
    payload = {
        "title": job.get("title"),
        "location": job.get("location"),
        "department": job.get("department") or job.get("team"),
        "description": job.get("description") or job.get("jd_text"),
        "apply_url": job.get("apply_url") or job.get("detail_url") or job.get("url"),
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _infer_seniority(text: str) -> str:
    for pattern, label in _SENIORITY_RULES:
        if re.search(pattern, text):
            return label
    return "IC"


def _infer_remote(text: str) -> str:
    for pattern, label in _REMOTE_RULES:
        if re.search(pattern, text):
            return label
    return "unknown"


def _infer_domain_tags(text: str) -> List[str]:
    tags = set()
    for pattern, label in _DOMAIN_TAG_RULES:
        if re.search(pattern, text):
            tags.add(label)
    return sorted(tags)


def _infer_level(text: str) -> Optional[str]:
    match = _LEVEL_RE.search(text)
    if match:
        return f"L{match.group(1)}"
    return None


def _normalize_location(location: Any) -> Optional[str]:
    loc_text = _normalize_text(location)
    if not loc_text:
        return None
    if "remote" in loc_text:
        return "remote"
    if "hybrid" in loc_text:
        return "hybrid"
    if re.search(r"\b(on[-\s]?site|in[-\s]?office)\b", loc_text):
        return "onsite"
    return " ".join(loc_text.split())


class EnrichmentCache:
    def __init__(self, cache_dir: Optional[Path]) -> None:
        self.cache_dir = cache_dir
        self.enabled = False
        if cache_dir is None:
            return
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
            test_file = cache_dir / ".write_test"
            test_file.write_text("ok", encoding="utf-8")
            test_file.unlink(missing_ok=True)
            self.enabled = True
        except Exception:
            self.enabled = False

    def _path_for(self, job_id: str) -> Path:
        digest = hashlib.sha256(job_id.encode("utf-8")).hexdigest()
        return self.cache_dir / f"{digest}.json"  # type: ignore[operator]

    def load(self, job_id: str, input_hash: str) -> Optional[Dict[str, Any]]:
        if not self.enabled:
            return None
        path = self._path_for(job_id)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        if payload.get("input_hash") != input_hash:
            return None
        return payload.get("enrichment")

    def store(self, job_id: str, input_hash: str, enrichment: Dict[str, Any]) -> None:
        if not self.enabled:
            return
        path = self._path_for(job_id)
        payload = {"input_hash": input_hash, "enrichment": enrichment}
        try:
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            return


def _default_cache_dir() -> Path:
    override = os.environ.get("JOBINTEL_CACHE_DIR")
    if override:
        return Path(override)
    return DATA_DIR / "ashby_cache"


def enrich_jobs(
    jobs: Iterable[Dict[str, Any]],
    cache_dir: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    cache = EnrichmentCache(cache_dir or _default_cache_dir())
    enriched: List[Dict[str, Any]] = []

    for job in jobs:
        job_id = _job_id(job)
        input_hash = _input_hash(job)
        cached = cache.load(job_id, input_hash)
        if cached is None:
            text = " ".join(
                _normalize_text(job.get(key))
                for key in ("title", "location", "department", "team", "description", "jd_text")
            )
            enrichment = {
                "inferred_seniority": _infer_seniority(text),
                "inferred_remote": _infer_remote(text),
                "inferred_domain_tags": _infer_domain_tags(text),
                "inferred_level": _infer_level(text),
                "normalized_location": _normalize_location(job.get("location")),
            }
            cache.store(job_id, input_hash, enrichment)
        else:
            enrichment = cached
        enriched.append({**job, "enrichment": enrichment})

    return enriched
