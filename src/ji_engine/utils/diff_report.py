"""
SignalCraft
Copyright (c) 2026 Chris Menendez.
All Rights Reserved.
See LICENSE for permitted use.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Iterable, List, Tuple

from .job_identity import job_identity, normalize_job_text

_DIFF_FIELDS: Tuple[str, ...] = ("title", "location", "team", "level", "score", "jd_hash")


def _normalize(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return normalize_job_text(value)
    return normalize_job_text(str(value))


def _job_description_text(job: Dict[str, Any]) -> str:
    return (
        job.get("description_text") or job.get("jd_text") or job.get("description") or job.get("descriptionHtml") or ""
    )


def _field_value(job: Dict[str, Any], field: str) -> str:
    if field == "location":
        return _normalize(job.get("location") or job.get("locationName"))
    if field == "level":
        return _normalize(job.get("level") or job.get("seniority"))
    if field == "score":
        score = job.get("score")
        if isinstance(score, (int, float)):
            return str(int(score))
        return ""
    if field == "jd_hash":
        text = _normalize(_job_description_text(job))
        if not text:
            return ""
        return hashlib.sha256(text.encode("utf-8")).hexdigest()
    return _normalize(job.get(field))


def _project(job: Dict[str, Any], identity: str) -> Dict[str, Any]:
    return {
        "id": identity,
        "provider": job.get("provider"),
        "job_id": job.get("job_id"),
        "title": job.get("title"),
        "location": job.get("location") or job.get("locationName"),
        "team": job.get("team") or job.get("department"),
        "apply_url": job.get("apply_url") or job.get("detail_url"),
        "score": job.get("score"),
    }


def _identity_key(job: Dict[str, Any]) -> str:
    jid = normalize_job_text(str(job.get("job_id") or ""), casefold=False)
    if jid:
        return jid
    return job_identity(job, mode="provider")


def _changed_fields(prev_job: Dict[str, Any], curr_job: Dict[str, Any]) -> List[str]:
    changed: List[str] = []
    for field in _DIFF_FIELDS:
        if _field_value(prev_job, field) != _field_value(curr_job, field):
            changed.append(field)
    return changed


def _stable_fingerprint(job: Dict[str, Any]) -> str:
    payload = {field: _field_value(job, field) for field in _DIFF_FIELDS}
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _sorted_items(items: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(items, key=lambda x: x.get("id") or "")


def build_diff_report(
    prev_jobs: List[Dict[str, Any]],
    curr_jobs: List[Dict[str, Any]],
    *,
    provider: str,
    profile: str,
    baseline_exists: bool,
    ignored_ids: set[str] | None = None,
) -> Dict[str, Any]:
    prev_map = {_identity_key(job): (job, _stable_fingerprint(job)) for job in prev_jobs}
    curr_map = {_identity_key(job): (job, _stable_fingerprint(job)) for job in curr_jobs}

    prev_ids = set(prev_map)
    curr_ids = set(curr_map)

    blocked = set(ignored_ids or set())
    added_ids = {identity for identity in (curr_ids - prev_ids) if identity not in blocked}
    removed_ids = {identity for identity in (prev_ids - curr_ids) if identity not in blocked}
    shared_ids = prev_ids & curr_ids

    changed_ids: List[str] = []
    changed_items: List[Dict[str, Any]] = []

    for identity in sorted(shared_ids):
        if identity in blocked:
            continue
        prev_job, prev_hash = prev_map[identity]
        curr_job, curr_hash = curr_map[identity]
        if prev_hash != curr_hash:
            changed_ids.append(identity)
            item = _project(curr_job, identity)
            item["changed_fields"] = _changed_fields(prev_job, curr_job)
            changed_items.append(item)

    added_items = [_project(curr_map[i][0], i) for i in added_ids]
    removed_items = [_project(prev_map[i][0], i) for i in removed_ids]

    report = {
        "provider": provider,
        "profile": profile,
        "baseline_exists": baseline_exists,
        "counts": {
            "added": len(added_items),
            "changed": len(changed_items),
            "removed": len(removed_items),
        },
        "added": _sorted_items(added_items),
        "changed": _sorted_items(changed_items),
        "removed": _sorted_items(removed_items),
        "suppressed": {
            "ignored": len(blocked & (prev_ids | curr_ids)),
        },
    }
    report["summary_hash"] = diff_report_digest(report)
    return report


def build_diff_markdown(report: Dict[str, Any], *, limit: int = 10) -> str:
    lines: List[str] = ["# Diff since last run"]
    if not report.get("baseline_exists"):
        lines.append("No previous run to diff against.")
        return "\n".join(lines) + "\n"

    counts = report.get("counts") or {}
    lines.append(
        f"Added: {counts.get('added', 0)} | Changed: {counts.get('changed', 0)} | Removed: {counts.get('removed', 0)}"
    )
    suppressed_ignored = int(((report.get("suppressed") or {}).get("ignored", 0)) or 0)
    if suppressed_ignored > 0:
        lines.append(f"Suppressed by user_state(ignore): {suppressed_ignored}")
    lines.append("")

    def _section(title: str, items: List[Dict[str, Any]]) -> None:
        lines.append(title)
        if not items:
            lines.append("- _None_")
            lines.append("")
            return
        for item in items[:limit]:
            title_val = item.get("title") or "Untitled"
            url = item.get("apply_url") or ""
            lines.append(f"- {title_val} — {url}")
        lines.append("")

    _section("## Added", report.get("added") or [])
    _section("## Changed", report.get("changed") or [])
    _section("## Removed", report.get("removed") or [])

    return "\n".join(lines)


def diff_report_digest(report: Dict[str, Any]) -> str:
    payload = dict(report)
    payload.pop("summary_hash", None)
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
