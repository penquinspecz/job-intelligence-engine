from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from ji_engine.utils.job_identity import job_identity, normalize_job_text, normalize_job_url

COMPLETENESS_FIELDS = (
    "job_id",
    "title",
    "location",
    "team",
    "apply_url",
    "detail_url",
)
DIFF_FIELDS = (
    "title",
    "location",
    "team",
    "apply_url",
    "detail_url",
    "job_id",
)
URL_FIELDS = {"apply_url", "detail_url", "url"}


@dataclass(frozen=True)
class NormalizedJob:
    job_id: str
    fingerprint: str
    fingerprint_fields: Dict[str, str]
    payload: Dict[str, Any]


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _normalize_value(field: str, value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        text = value.strip()
        if field in URL_FIELDS:
            return normalize_job_url(text)
        return text
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
    return str(value).strip()


def _effective_provider(job: Dict[str, Any]) -> str:
    provider = job.get("provider") or job.get("source") or ""
    return _stringify(provider)


def _effective_job_id(job: Dict[str, Any]) -> str:
    raw = job.get("job_id")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return job_identity(job, mode="provider")


def _fingerprint_fields(job: Dict[str, Any]) -> Dict[str, str]:
    provider = _effective_provider(job)
    url = ""
    for field in ("apply_url", "detail_url", "url"):
        candidate = _normalize_value(field, job.get(field))
        if candidate:
            url = candidate
            break
    title = normalize_job_text(_stringify(job.get("title") or ""), casefold=True)
    location = normalize_job_text(_stringify(job.get("location") or ""), casefold=True)
    team = normalize_job_text(_stringify(job.get("team") or ""), casefold=True)
    return {
        "provider": provider,
        "url": url,
        "title": title,
        "location": location,
        "team": team,
    }


def _fingerprint(job: Dict[str, Any]) -> str:
    payload = _fingerprint_fields(job)
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _normalize_jobs(jobs: Iterable[Dict[str, Any]]) -> List[NormalizedJob]:
    normalized: List[NormalizedJob] = []
    for job in jobs:
        if not isinstance(job, dict):
            continue
        job_id = _effective_job_id(job)
        fingerprint_fields = _fingerprint_fields(job)
        normalized.append(
            NormalizedJob(
                job_id=job_id,
                fingerprint=_fingerprint(job),
                fingerprint_fields=fingerprint_fields,
                payload=dict(job),
            )
        )
    normalized.sort(key=lambda item: (item.job_id, _normalize_value("apply_url", item.payload.get("apply_url"))))
    return normalized


def _resolve_ranked_json_path(run_report: Dict[str, Any], report_path: Path, provider: str, profile: str) -> Path:
    outputs_by_provider = run_report.get("outputs_by_provider")
    profile_outputs: Dict[str, Any] | None = None
    if isinstance(outputs_by_provider, dict):
        provider_outputs = outputs_by_provider.get(provider)
        if isinstance(provider_outputs, dict):
            maybe_profile = provider_outputs.get(profile)
            if isinstance(maybe_profile, dict):
                profile_outputs = maybe_profile

    if profile_outputs is None:
        outputs_by_profile = run_report.get("outputs_by_profile")
        if isinstance(outputs_by_profile, dict):
            maybe_profile = outputs_by_profile.get(profile)
            if isinstance(maybe_profile, dict):
                profile_outputs = maybe_profile

    if profile_outputs is None:
        raise ValueError(f"run report missing outputs for '{provider}:{profile}'")

    ranked_json = profile_outputs.get("ranked_json")
    if not isinstance(ranked_json, dict):
        raise ValueError("run report missing ranked_json output")
    raw_path = ranked_json.get("path")
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise ValueError("run report ranked_json path is empty")
    path = Path(raw_path)
    if path.exists():
        return path
    candidate = report_path.parent / raw_path
    if candidate.exists():
        return candidate
    raise ValueError(f"ranked_json path not found: {raw_path}")


def _pick_single(values: Iterable[str], label: str) -> str:
    unique = sorted({value for value in values if value})
    if len(unique) != 1:
        raise ValueError(f"run report has multiple {label} values; pass --{label}")
    return unique[0]


def _load_jobs_from_run_report(
    report_path: Path,
    report: Dict[str, Any],
    *,
    provider: Optional[str],
    profile: Optional[str],
) -> List[Dict[str, Any]]:
    providers = report.get("providers") or []
    profiles = report.get("profiles") or []
    provider_id = provider or _pick_single(providers, "provider")
    profile_id = profile or _pick_single(profiles, "profile")
    ranked_path = _resolve_ranked_json_path(report, report_path, provider_id, profile_id)
    payload = _read_json(ranked_path)
    if not isinstance(payload, list):
        raise ValueError(f"ranked jobs payload at {ranked_path} is not a list")
    return [item for item in payload if isinstance(item, dict)]


def load_jobs_from_path(
    path: Path,
    *,
    provider: Optional[str] = None,
    profile: Optional[str] = None,
) -> List[Dict[str, Any]]:
    if path.is_dir():
        report_path = path / "run_report.json"
        if report_path.exists():
            report = _read_json(report_path)
            if not isinstance(report, dict):
                raise ValueError(f"run report at {report_path} is not an object")
            return _load_jobs_from_run_report(report_path, report, provider=provider, profile=profile)
        raise ValueError(f"directory {path} does not contain run_report.json")
    if not path.exists():
        raise ValueError(f"file not found: {path}")
    payload = _read_json(path)
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        if payload.get("run_report_schema_version"):
            return _load_jobs_from_run_report(path, payload, provider=provider, profile=profile)
        if isinstance(payload.get("jobs"), list):
            return [item for item in payload.get("jobs") if isinstance(item, dict)]
    raise ValueError(f"unsupported payload at {path}; expected list of jobs or run report")


def _group_jobs_by_id(jobs: Iterable[NormalizedJob]) -> Dict[str, List[NormalizedJob]]:
    grouped: Dict[str, List[NormalizedJob]] = defaultdict(list)
    for job in jobs:
        grouped[job.job_id].append(job)
    for job_id, items in grouped.items():
        items.sort(
            key=lambda item: (
                item.fingerprint,
                _normalize_value("apply_url", item.payload.get("apply_url")),
                _normalize_value("detail_url", item.payload.get("detail_url")),
            )
        )
        grouped[job_id] = items
    return grouped


def _field_diff(baseline: Dict[str, Any], candidate: Dict[str, Any]) -> Dict[str, Dict[str, str]]:
    diffs: Dict[str, Dict[str, str]] = {}
    for field in DIFF_FIELDS:
        base_value = _normalize_value(field, baseline.get(field))
        cand_value = _normalize_value(field, candidate.get(field))
        if base_value != cand_value:
            diffs[field] = {"baseline": base_value, "candidate": cand_value}
    return diffs


def _field_completeness(jobs: Iterable[NormalizedJob], total: int) -> Dict[str, Dict[str, float]]:
    counts = dict.fromkeys(COMPLETENESS_FIELDS, 0)
    for job in jobs:
        for field in COMPLETENESS_FIELDS:
            value = _normalize_value(field, job.payload.get(field))
            if value:
                counts[field] += 1
    output: Dict[str, Dict[str, float]] = {}
    for field in COMPLETENESS_FIELDS:
        non_empty = counts[field]
        percent = round(non_empty / total, 4) if total else 0.0
        output[field] = {"non_empty": float(non_empty), "total": float(total), "percent": percent}
    return output


def _delta_completeness(
    baseline: Dict[str, Dict[str, float]],
    candidate: Dict[str, Dict[str, float]],
) -> Dict[str, float]:
    delta: Dict[str, float] = {}
    for field in COMPLETENESS_FIELDS:
        delta[field] = round(candidate[field]["percent"] - baseline[field]["percent"], 4)
    return delta


def _job_id_churn(
    baseline: Iterable[NormalizedJob],
    candidate: Iterable[NormalizedJob],
    *,
    limit: int = 5,
) -> Dict[str, Any]:
    baseline_map = {job.fingerprint: job for job in baseline}
    candidate_map = {job.fingerprint: job for job in candidate}
    overlaps = sorted(set(baseline_map.keys()) & set(candidate_map.keys()))
    churned: List[Dict[str, Any]] = []
    for fingerprint in overlaps:
        base_job = baseline_map[fingerprint]
        cand_job = candidate_map[fingerprint]
        if base_job.job_id != cand_job.job_id:
            churned.append(
                {
                    "fingerprint": fingerprint,
                    "baseline_job_id": base_job.job_id,
                    "candidate_job_id": cand_job.job_id,
                    "identity_hint": base_job.fingerprint_fields,
                }
            )
    churned.sort(key=lambda item: (item["baseline_job_id"], item["candidate_job_id"]))
    overlap_count = len(overlaps)
    churn_count = len(churned)
    churn_rate = round(churn_count / overlap_count, 4) if overlap_count else 0.0
    return {
        "overlap_fingerprints": overlap_count,
        "churn_count": churn_count,
        "churn_rate": churn_rate,
        "examples": churned[:limit],
    }


def _risk_score(
    *,
    baseline_total: int,
    candidate_total: int,
    churn_rate: float,
    apply_url_delta: float,
    candidate_apply_url_percent: float,
    changed_ratio: float,
) -> Tuple[int, List[str]]:
    score = 0
    reasons: List[str] = []
    if baseline_total:
        drop_ratio = (baseline_total - candidate_total) / baseline_total
        if drop_ratio >= 0.6:
            score += 40
            reasons.append("job_count_drop>=60%")
        elif drop_ratio >= 0.3:
            score += 20
            reasons.append("job_count_drop>=30%")
    if churn_rate >= 0.3:
        score += 30
        reasons.append("job_id_churn>=30%")
    elif churn_rate >= 0.1:
        score += 15
        reasons.append("job_id_churn>=10%")
    if apply_url_delta <= -0.2:
        score += 15
        reasons.append("apply_url_completeness_drop>=20%")
    if candidate_apply_url_percent < 0.8:
        score += 10
        reasons.append("apply_url_completeness<80%")
    if changed_ratio >= 0.5:
        score += 10
        reasons.append("field_changes>=50%")
    return min(score, 100), reasons


def build_safety_diff_report(
    baseline_jobs: Iterable[Dict[str, Any]],
    candidate_jobs: Iterable[Dict[str, Any]],
    *,
    baseline_path: str,
    candidate_path: str,
    top_n: int = 5,
) -> Dict[str, Any]:
    baseline_norm = _normalize_jobs(baseline_jobs)
    candidate_norm = _normalize_jobs(candidate_jobs)
    baseline_total = len(baseline_norm)
    candidate_total = len(candidate_norm)
    baseline_grouped = _group_jobs_by_id(baseline_norm)
    candidate_grouped = _group_jobs_by_id(candidate_norm)
    baseline_counts = Counter(job.job_id for job in baseline_norm)
    candidate_counts = Counter(job.job_id for job in candidate_norm)
    all_ids = sorted(set(baseline_counts) | set(candidate_counts))
    common_ids = sorted(set(baseline_grouped.keys()) & set(candidate_grouped.keys()))

    changes: List[Dict[str, Any]] = []
    for job_id in common_ids:
        baseline_jobs_for_id = baseline_grouped[job_id]
        candidate_jobs_for_id = candidate_grouped[job_id]
        pair_count = min(len(baseline_jobs_for_id), len(candidate_jobs_for_id))
        for idx in range(pair_count):
            baseline_job = baseline_jobs_for_id[idx]
            candidate_job = candidate_jobs_for_id[idx]
            diffs = _field_diff(baseline_job.payload, candidate_job.payload)
            if diffs:
                changes.append(
                    {
                        "job_id": job_id,
                        "diff_count": len(diffs),
                        "field_diffs": {field: diffs[field] for field in sorted(diffs)},
                    }
                )
    changes.sort(key=lambda item: (-item["diff_count"], item["job_id"]))

    churn = _job_id_churn(baseline_norm, candidate_norm, limit=top_n)
    baseline_completeness = _field_completeness(baseline_norm, baseline_total)
    candidate_completeness = _field_completeness(candidate_norm, candidate_total)
    delta_completeness = _delta_completeness(baseline_completeness, candidate_completeness)
    common_occurrence_count = sum(min(baseline_counts[job_id], candidate_counts[job_id]) for job_id in all_ids)
    changed_ratio = round(len(changes) / common_occurrence_count, 4) if common_occurrence_count else 0.0
    new_count = sum(max(candidate_counts[job_id] - baseline_counts[job_id], 0) for job_id in all_ids)
    removed_count = sum(max(baseline_counts[job_id] - candidate_counts[job_id], 0) for job_id in all_ids)

    apply_url_delta = delta_completeness["apply_url"]
    candidate_apply_url_percent = candidate_completeness["apply_url"]["percent"]
    risk_score, risk_reasons = _risk_score(
        baseline_total=baseline_total,
        candidate_total=candidate_total,
        churn_rate=churn["churn_rate"],
        apply_url_delta=apply_url_delta,
        candidate_apply_url_percent=candidate_apply_url_percent,
        changed_ratio=changed_ratio,
    )

    return {
        "schema_version": 1,
        "baseline": {"path": baseline_path, "total_jobs": baseline_total},
        "candidate": {"path": candidate_path, "total_jobs": candidate_total},
        "counts": {
            "baseline_total": baseline_total,
            "candidate_total": candidate_total,
            "new": new_count,
            "removed": removed_count,
            "changed": len(changes),
        },
        "job_id_churn": churn,
        "field_completeness": {
            "fields": list(COMPLETENESS_FIELDS),
            "baseline": baseline_completeness,
            "candidate": candidate_completeness,
            "delta": delta_completeness,
        },
        "changes_top": changes[:top_n],
        "risk_score": risk_score,
        "risk_reasons": risk_reasons,
    }


def render_summary(report: Dict[str, Any]) -> str:
    counts = report.get("counts", {})
    churn = report.get("job_id_churn", {})
    risk_score = report.get("risk_score", 0)
    risk_reasons = report.get("risk_reasons", [])
    reasons = ", ".join(risk_reasons) if risk_reasons else "none"
    return "\n".join(
        [
            "Safety diff summary",
            f"- baseline_total={counts.get('baseline_total', 0)} candidate_total={counts.get('candidate_total', 0)}",
            f"- new={counts.get('new', 0)} removed={counts.get('removed', 0)} changed={counts.get('changed', 0)}",
            f"- job_id_churn={churn.get('churn_count', 0)} rate={churn.get('churn_rate', 0)}",
            f"- risk_score={risk_score} reasons={reasons}",
        ]
    )


def write_report(report: Dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
