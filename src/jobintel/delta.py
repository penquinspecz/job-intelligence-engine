from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


FIELDS = ("title", "location", "team", "url")
MAX_ID_LIST = 20


def _load_list(path: Optional[Path]) -> List[Dict[str, Any]]:
    if not path or not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    return []


def _normalize(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped.lower() if stripped else None
    return str(value).strip().lower()


def _extract_url(job: Dict[str, Any]) -> Optional[str]:
    for key in ("apply_url", "detail_url", "url"):
        value = job.get(key)
        if value:
            return str(value)
    return None


def extract_job_id(job: Dict[str, Any], provider: str) -> str:
    for key in ("job_id", "id"):
        value = job.get(key)
        if value:
            return f"{provider}:{value}"
    url = _extract_url(job)
    if url:
        return f"{provider}:{url}"
    base = {
        "title": job.get("title"),
        "location": job.get("location"),
        "team": job.get("team"),
    }
    digest = hashlib.sha256(json.dumps(base, sort_keys=True).encode("utf-8")).hexdigest()
    return f"{provider}:hash:{digest}"


def extract_fields(job: Dict[str, Any]) -> Dict[str, Optional[str]]:
    return {
        "title": _normalize(job.get("title")),
        "location": _normalize(job.get("location")),
        "team": _normalize(job.get("team")),
        "url": _normalize(_extract_url(job)),
    }


def _cap_list(values: Iterable[str], limit: int = MAX_ID_LIST) -> List[str]:
    sorted_vals = sorted(values)
    return sorted_vals[:limit]


def compute_delta(
    current_labeled_path: Optional[Path],
    current_ranked_path: Optional[Path],
    baseline_labeled_path: Optional[Path],
    baseline_ranked_path: Optional[Path],
    provider: str,
    profile: str,
) -> Dict[str, Any]:
    current_labeled = _load_list(current_labeled_path)
    current_ranked = _load_list(current_ranked_path)
    baseline_ranked = _load_list(baseline_ranked_path)

    labeled_total = len(current_labeled)
    ranked_total = len(current_ranked)

    if not baseline_ranked:
        return {
            "provider": provider,
            "profile": profile,
            "labeled_total": labeled_total,
            "ranked_total": ranked_total,
            "new_job_count": 0,
            "removed_job_count": 0,
            "changed_job_count": 0,
            "unchanged_job_count": 0,
            "new_job_ids": [],
            "removed_job_ids": [],
            "changed_job_ids": [],
            "change_fields": {"title": 0, "location": 0, "team": 0, "url": 0},
        }

    current_map = {extract_job_id(job, provider): job for job in current_ranked}
    baseline_map = {extract_job_id(job, provider): job for job in baseline_ranked}

    current_ids = set(current_map)
    baseline_ids = set(baseline_map)

    new_ids = current_ids - baseline_ids
    removed_ids = baseline_ids - current_ids
    intersect_ids = current_ids & baseline_ids

    change_fields = {"title": 0, "location": 0, "team": 0, "url": 0}
    changed_ids: List[str] = []
    unchanged_ids: List[str] = []

    for job_id in sorted(intersect_ids):
        current_fields = extract_fields(current_map[job_id])
        baseline_fields = extract_fields(baseline_map[job_id])
        changed = False
        for field in FIELDS:
            if current_fields.get(field) != baseline_fields.get(field):
                change_fields[field] += 1
                changed = True
        if changed:
            changed_ids.append(job_id)
        else:
            unchanged_ids.append(job_id)

    return {
        "provider": provider,
        "profile": profile,
        "labeled_total": labeled_total,
        "ranked_total": ranked_total,
        "new_job_count": len(new_ids),
        "removed_job_count": len(removed_ids),
        "changed_job_count": len(changed_ids),
        "unchanged_job_count": len(unchanged_ids),
        "new_job_ids": _cap_list(new_ids),
        "removed_job_ids": _cap_list(removed_ids),
        "changed_job_ids": _cap_list(changed_ids),
        "change_fields": change_fields,
    }
