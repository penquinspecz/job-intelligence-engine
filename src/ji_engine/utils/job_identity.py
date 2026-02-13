"""
SignalCraft
Copyright (c) 2026 Chris Menendez.
All Rights Reserved.
See LICENSE for permitted use.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Dict, Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_DROP_QUERY_PREFIXES = ("utm_", "gh_", "lever_")
_DROP_QUERY_KEYS = {
    "gh_jid",
    "gh_src",
    "gh_source",
    "lever-source",
    "lever_source",
    "source",
    "sourceid",
    "ref",
    "referrer",
    "icid",
    "mc_cid",
    "mc_eid",
}

_REQUISITION_KEYS = (
    "requisition_id",
    "requisitionId",
    "req_id",
    "reqId",
    "job_requisition_id",
    "jobRequisitionId",
    "applyId",
    "id",
)
_PLAIN_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._:-]{1,127}$", re.IGNORECASE)


def normalize_job_text(value: str, *, casefold: bool = True) -> str:
    normalized = " ".join(value.split()).strip()
    return normalized.casefold() if casefold else normalized


def _should_drop_param(key: str) -> bool:
    lowered = key.casefold()
    if lowered in _DROP_QUERY_KEYS:
        return True
    return any(lowered.startswith(prefix) for prefix in _DROP_QUERY_PREFIXES)


def normalize_job_url(value: str) -> str:
    normalized = normalize_job_text(value, casefold=False)
    if not normalized:
        return ""
    parts = urlsplit(normalized)
    scheme = parts.scheme.lower()
    netloc = parts.netloc.lower()
    path = parts.path.rstrip("/")
    query_pairs = parse_qsl(parts.query, keep_blank_values=True)
    filtered = [(key, val) for key, val in query_pairs if key and not _should_drop_param(key)]
    filtered.sort(key=lambda item: (item[0].casefold(), item[1]))
    query = urlencode(filtered, doseq=True)
    return urlunsplit((scheme, netloc, path, query, ""))


def _norm(value: Any, *, lower: bool = True) -> str:
    text = normalize_job_text(str(value), casefold=False)
    if not text:
        return ""
    return text.casefold() if lower else text


def _provider_name(job: Dict[str, object], *, mode: Literal["legacy", "provider"]) -> str:
    if mode != "provider":
        return ""
    provider = job.get("provider") or job.get("source") or ""
    return _norm(provider)


def _extract_requisition_id(job: Dict[str, object]) -> str:
    for key in _REQUISITION_KEYS:
        value = job.get(key)
        if value is None:
            continue
        normalized = _norm(value)
        if not normalized:
            continue
        if normalized.startswith(("http://", "https://", "/")):
            continue
        if _PLAIN_ID_RE.fullmatch(normalized):
            return normalized

    job_id = job.get("job_id")
    if isinstance(job_id, str):
        normalized = _norm(job_id)
        if normalized and _PLAIN_ID_RE.fullmatch(normalized):
            return normalized
    return ""


def _description_hash(job: Dict[str, object]) -> str:
    description = (
        job.get("description_text") or job.get("jd_text") or job.get("description") or job.get("descriptionHtml") or ""
    )
    normalized = _norm(description)
    if not normalized:
        return ""
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _legacy_identity(job: Dict[str, object]) -> str:
    for key in ("job_id",):
        value = job.get(key)
        if value is not None:
            normalized = normalize_job_text(str(value), casefold=False)
            if normalized:
                return normalized

    for field in ("apply_url", "detail_url", "url"):
        value = job.get(field)
        if isinstance(value, str):
            normalized = normalize_job_url(value)
            if normalized:
                return normalized

    for key in ("id", "applyId"):
        value = job.get(key)
        if value is not None:
            normalized = normalize_job_text(str(value), casefold=False)
            if normalized:
                return normalized

    title = _norm(job.get("title"))
    location = _norm(job.get("location") or job.get("locationName"))
    team = _norm(job.get("team") or job.get("department") or job.get("departmentName"))
    payload = {"strategy": "legacy_fallback", "title": title, "location": location, "team": team}
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def job_identity(job: Dict[str, object], *, mode: Literal["legacy", "provider"] = "legacy") -> str:
    """
    Deterministic identifier for job postings.

    Strategy (in priority order):
    1. provider + stable requisition/id field (when present)
    2. provider + canonical URL + normalized title/location/team
    3. provider + normalized title/location/team + JD hash fallback

    URL normalization removes known tracking params and fragments.
    Text normalization is whitespace/case insensitive.
    """

    if mode == "legacy":
        return _legacy_identity(job)

    provider = _provider_name(job, mode=mode)
    title = _norm(job.get("title"))
    location = _norm(job.get("location") or job.get("locationName"))
    team = _norm(job.get("team") or job.get("department") or job.get("departmentName"))
    canonical_url = ""
    for field in ("apply_url", "detail_url", "url"):
        value = job.get(field)
        if isinstance(value, str):
            normalized = normalize_job_url(value)
            if normalized:
                canonical_url = normalized
                break

    requisition_id = _extract_requisition_id(job)
    payload: Dict[str, object]
    if requisition_id:
        payload = {
            "strategy": "provider_requisition",
            "provider": provider,
            "requisition_id": requisition_id,
        }
    elif canonical_url:
        payload = {
            "strategy": "provider_url_fields",
            "provider": provider,
            "canonical_url": canonical_url,
            "title": title,
            "location": location,
            "team": team,
        }
    else:
        payload = {
            "strategy": "provider_content_fallback",
            "provider": provider,
            "title": title,
            "location": location,
            "team": team,
            "jd_hash": _description_hash(job),
        }

    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()
