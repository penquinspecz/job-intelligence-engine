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
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ji_engine.config import RUN_METADATA_DIR
from ji_engine.utils.time import utc_now_z

_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9+#.-]*")
_TRACKED_DIFF_FIELDS = ("title", "location", "team", "score", "final_score", "role_band")
_SKILL_KEYWORDS = {
    "ai",
    "ml",
    "llm",
    "nlp",
    "python",
    "sql",
    "docker",
    "kubernetes",
    "aws",
    "gcp",
    "azure",
    "terraform",
    "postgres",
    "snowflake",
    "spark",
    "pytorch",
    "tensorflow",
    "java",
    "javascript",
    "typescript",
    "react",
    "go",
    "rust",
}


def _utcnow_iso() -> str:
    return utc_now_z(seconds_precision=True)


def _sanitize_run_id(run_id: str) -> str:
    return run_id.replace(":", "").replace("-", "").replace(".", "")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_path(path: Optional[Path]) -> Optional[str]:
    if not path or not path.exists():
        return None
    return _sha256_bytes(path.read_bytes())


def _load_jobs(path: Optional[Path]) -> List[Dict[str, Any]]:
    if not path or not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


def _job_id(job: Dict[str, Any]) -> str:
    value = str(job.get("job_id") or "").strip()
    if value:
        return value
    fallback = str(job.get("apply_url") or job.get("detail_url") or job.get("title") or "").strip()
    return fallback or "missing:unknown"


def _job_title(job: Dict[str, Any]) -> str:
    return str(job.get("title") or "Untitled").strip() or "Untitled"


def _job_score(job: Dict[str, Any]) -> int:
    return int(job.get("score", 0) or 0)


def _stable_role(job: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "title": _job_title(job),
        "score": _job_score(job),
        "apply_url": str(job.get("apply_url") or ""),
    }


def _top_roles(jobs: List[Dict[str, Any]], limit: int = 5) -> List[Dict[str, Any]]:
    ordered = sorted(
        jobs,
        key=lambda job: (
            -_job_score(job),
            _job_title(job).lower(),
            str(job.get("apply_url") or "").lower(),
            _job_id(job).lower(),
        ),
    )
    return [_stable_role(job) for job in ordered[:limit]]


def _score_distribution(jobs: List[Dict[str, Any]]) -> Dict[str, Any]:
    buckets = {"gte90": 0, "gte80": 0, "gte70": 0, "gte60": 0, "lt60": 0}
    for job in jobs:
        score = _job_score(job)
        if score >= 90:
            buckets["gte90"] += 1
        elif score >= 80:
            buckets["gte80"] += 1
        elif score >= 70:
            buckets["gte70"] += 1
        elif score >= 60:
            buckets["gte60"] += 1
        else:
            buckets["lt60"] += 1
    return {"total": len(jobs), "buckets": buckets}


def _median_score(jobs: List[Dict[str, Any]]) -> float:
    scores = sorted(_job_score(job) for job in jobs)
    if not scores:
        return 0.0
    mid = len(scores) // 2
    if len(scores) % 2 == 1:
        return float(scores[mid])
    return float((scores[mid - 1] + scores[mid]) / 2.0)


def _is_changed(curr: Dict[str, Any], prev: Dict[str, Any]) -> bool:
    for field in _TRACKED_DIFF_FIELDS:
        if str(curr.get(field) or "") != str(prev.get(field) or ""):
            return True
    return False


def _top_titles(jobs: List[Dict[str, Any]], limit: int = 5) -> List[str]:
    ordered = sorted(
        jobs,
        key=lambda job: (
            -_job_score(job),
            _job_title(job).lower(),
            _job_id(job).lower(),
        ),
    )
    return [_job_title(job) for job in ordered[:limit]]


def _diff_summary(curr_jobs: List[Dict[str, Any]], prev_jobs: List[Dict[str, Any]]) -> Dict[str, Any]:
    curr_map = {_job_id(job): job for job in curr_jobs}
    prev_map = {_job_id(job): job for job in prev_jobs}
    curr_ids = set(curr_map.keys())
    prev_ids = set(prev_map.keys())

    new_ids = sorted(curr_ids - prev_ids)
    removed_ids = sorted(prev_ids - curr_ids)
    changed_ids = sorted(
        [job_id for job_id in (curr_ids & prev_ids) if _is_changed(curr_map[job_id], prev_map[job_id])]
    )
    return {
        "counts": {"new": len(new_ids), "changed": len(changed_ids), "removed": len(removed_ids)},
        "top_new_titles": _top_titles([curr_map[job_id] for job_id in new_ids]),
        "top_changed_titles": _top_titles([curr_map[job_id] for job_id in changed_ids]),
        "top_removed_titles": _top_titles([prev_map[job_id] for job_id in removed_ids]),
    }


def _top_families(jobs: List[Dict[str, Any]], limit: int = 8) -> List[Dict[str, Any]]:
    counts: Dict[str, int] = {}
    for job in jobs:
        family = str(job.get("title_family") or "").strip()
        if not family:
            continue
        counts[family] = counts.get(family, 0) + 1
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0].lower()))
    return [{"family": family, "count": count} for family, count in ordered[:limit]]


def _skill_keywords(jobs: List[Dict[str, Any]], limit: int = 12) -> List[Dict[str, Any]]:
    counts: Dict[str, int] = {}
    for job in jobs:
        text_parts: List[str] = [str(job.get("title") or "")]
        for field in ("fit_signals", "risk_signals"):
            values = job.get(field) or []
            if isinstance(values, list):
                text_parts.extend(str(value) for value in values)
        ai_payload = job.get("ai") or {}
        if isinstance(ai_payload, dict):
            for field in ("skills_required", "skills_preferred"):
                values = ai_payload.get(field) or []
                if isinstance(values, list):
                    text_parts.extend(str(value) for value in values)
        tokens = _TOKEN_RE.findall(" ".join(text_parts).lower())
        for token in tokens:
            if token in _SKILL_KEYWORDS:
                counts[token] = counts.get(token, 0) + 1
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [{"keyword": keyword, "count": count} for keyword, count in ordered[:limit]]


def _top_recurring_skill_tokens(jobs: List[Dict[str, Any]], limit: int = 3) -> List[Dict[str, Any]]:
    return _skill_keywords(jobs, limit=limit)


def _rolling_diff_counts_7(provider: str, profile: str, *, run_limit: int = 7) -> Dict[str, Any]:
    run_reports = sorted(RUN_METADATA_DIR.glob("*.json"), key=lambda p: p.name, reverse=True)
    series: List[Dict[str, Any]] = []
    totals = {"new": 0, "changed": 0, "removed": 0}
    for path in run_reports:
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(report, dict):
            continue
        provider_map = ((report.get("delta_summary") or {}).get("provider_profile") or {}).get(provider) or {}
        profile_entry = provider_map.get(profile) or {}
        try:
            new_count = int(profile_entry.get("new_job_count", 0) or 0)
            changed_count = int(profile_entry.get("changed_job_count", 0) or 0)
            removed_count = int(profile_entry.get("removed_job_count", 0) or 0)
        except Exception:
            continue
        series.append(
            {
                "run_id": str(report.get("run_id") or path.stem),
                "new": new_count,
                "changed": changed_count,
                "removed": removed_count,
            }
        )
        totals["new"] += new_count
        totals["changed"] += changed_count
        totals["removed"] += removed_count
        if len(series) >= run_limit:
            break
    series.reverse()
    return {"window_size": run_limit, "runs_considered": len(series), "totals": totals, "series": series}


def build_weekly_insights_input(
    *,
    provider: str,
    profile: str,
    ranked_path: Path,
    prev_path: Optional[Path],
    ranked_families_path: Optional[Path],
    run_id: str,
    run_metadata_dir: Path = RUN_METADATA_DIR,
) -> Tuple[Path, Dict[str, Any]]:
    curr_jobs = _load_jobs(ranked_path)
    prev_jobs = _load_jobs(prev_path)
    family_jobs = _load_jobs(ranked_families_path)

    current_median = _median_score(curr_jobs)
    previous_median = _median_score(prev_jobs)
    payload: Dict[str, Any] = {
        "schema_version": 1,
        "generated_at": _utcnow_iso(),
        "run_id": run_id,
        "provider": provider,
        "profile": profile,
        "input_hashes": {
            "ranked": _sha256_path(ranked_path),
            "previous": _sha256_path(prev_path),
            "ranked_families": _sha256_path(ranked_families_path),
        },
        "diffs": _diff_summary(curr_jobs, prev_jobs),
        "top_roles": _top_roles(curr_jobs),
        "top_families": _top_families(family_jobs if family_jobs else curr_jobs),
        "score_distribution": _score_distribution(curr_jobs),
        "skill_keywords": _skill_keywords(curr_jobs),
        "rolling_diff_counts_7": _rolling_diff_counts_7(provider, profile, run_limit=7),
        "top_recurring_skill_tokens": _top_recurring_skill_tokens(curr_jobs, limit=3),
        "median_score_trend_delta": {
            "current_median": current_median,
            "previous_median": previous_median,
            "delta": round(current_median - previous_median, 3),
        },
    }

    run_dir = run_metadata_dir / _sanitize_run_id(run_id)
    out_path = run_dir / "ai" / f"insights_input.{profile}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return out_path, payload
