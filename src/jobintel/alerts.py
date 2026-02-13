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
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from ji_engine.utils.job_identity import job_identity


def _normalize(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split()).strip().lower()


def stable_title_location_hash(job: Dict[str, Any]) -> str:
    payload = {
        "title": _normalize(job.get("title")),
        "location": _normalize(job.get("location") or job.get("locationName")),
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _job_url(job: Dict[str, Any]) -> Optional[str]:
    for key in ("apply_url", "detail_url", "url"):
        value = job.get(key)
        if value:
            return str(value)
    return None


def build_last_seen(jobs: Iterable[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    index: Dict[str, Dict[str, Any]] = {}
    for job in jobs:
        jid = job_identity(job)
        index[jid] = {
            "score": job.get("score"),
            "title_hash": stable_title_location_hash(job),
            "updated_at": job.get("updated_at") or job.get("updated_at_iso"),
        }
    return index


def load_last_seen(path: Path) -> Dict[str, Dict[str, Any]]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if isinstance(payload, dict):
        return {str(k): v for k, v in payload.items() if isinstance(v, dict)}
    return {}


def write_last_seen(path: Path, index: Dict[str, Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(index, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _sort_jobs(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(
        items,
        key=lambda j: (
            -(j.get("score") or 0),
            j.get("title") or "",
            j.get("job_id") or "",
        ),
    )


def compute_alerts(
    jobs: Iterable[Dict[str, Any]],
    prev_index: Dict[str, Dict[str, Any]],
    score_delta: int = 10,
) -> Dict[str, Any]:
    current_jobs = list(jobs)
    current_index = build_last_seen(current_jobs)

    new_jobs: List[Dict[str, Any]] = []
    removed_jobs: List[str] = []
    score_changes: List[Dict[str, Any]] = []
    title_location_changes: List[Dict[str, Any]] = []

    for job in current_jobs:
        jid = job_identity(job)
        prev = prev_index.get(jid)
        if prev is None:
            new_jobs.append(
                {
                    "job_id": jid,
                    "title": job.get("title"),
                    "score": job.get("score"),
                    "url": _job_url(job),
                }
            )
            continue
        prev_score = prev.get("score")
        curr_score = job.get("score")
        if isinstance(prev_score, (int, float)) and isinstance(curr_score, (int, float)):
            delta = curr_score - prev_score
            if abs(delta) >= score_delta:
                score_changes.append(
                    {
                        "job_id": jid,
                        "title": job.get("title"),
                        "score": curr_score,
                        "prev_score": prev_score,
                        "delta": delta,
                        "url": _job_url(job),
                    }
                )
        if prev.get("title_hash") != current_index[jid].get("title_hash"):
            title_location_changes.append(
                {
                    "job_id": jid,
                    "title": job.get("title"),
                    "score": job.get("score"),
                    "url": _job_url(job),
                }
            )

    for jid in sorted(prev_index.keys()):
        if jid not in current_index:
            removed_jobs.append(jid)

    new_jobs_sorted = _sort_jobs(new_jobs)
    score_changes_sorted = _sort_jobs(score_changes)
    title_changes_sorted = _sort_jobs(title_location_changes)

    return {
        "counts": {
            "new": len(new_jobs_sorted),
            "removed": len(removed_jobs),
            "score_changes": len(score_changes_sorted),
            "title_or_location_changes": len(title_changes_sorted),
        },
        "new_jobs": new_jobs_sorted,
        "removed_jobs": removed_jobs,
        "score_changes": score_changes_sorted,
        "title_or_location_changes": title_changes_sorted,
    }


def write_alerts(
    json_path: Path,
    md_path: Path,
    alerts: Dict[str, Any],
    provider: str,
    profile: str,
) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(alerts, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")

    def _fmt_line(job: Dict[str, Any]) -> str:
        title = job.get("title") or "Untitled"
        url = job.get("url") or ""
        score = job.get("score")
        score_part = f" (score {score})" if isinstance(score, (int, float)) else ""
        return f"- {title}{score_part} — {url}" if url else f"- {title}{score_part}"

    counts = alerts.get("counts", {})
    lines = [
        f"# Alerts ({provider}/{profile})",
        "",
        f"- New: {counts.get('new', 0)}",
        f"- Removed: {counts.get('removed', 0)}",
        f"- Score changes: {counts.get('score_changes', 0)}",
        f"- Title/location changes: {counts.get('title_or_location_changes', 0)}",
        "",
    ]

    for label, key in (
        ("New jobs", "new_jobs"),
        ("Score changes", "score_changes"),
        ("Title/location changes", "title_or_location_changes"),
    ):
        items = alerts.get(key, [])[:10]
        lines.append(f"## {label}")
        if not items:
            lines.append("- none")
        else:
            lines.extend(_fmt_line(item) for item in items)
        lines.append("")

    lines.append("## Removed jobs")
    removed = alerts.get("removed_jobs", [])[:10]
    if removed:
        for jid in removed:
            lines.append(f"- {jid}")
    else:
        lines.append("- none")

    md_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def resolve_score_delta() -> int:
    raw = os.environ.get("JOBINTEL_ALERT_SCORE_DELTA")
    if raw is None:
        return 10
    try:
        return int(raw)
    except ValueError:
        return 10
