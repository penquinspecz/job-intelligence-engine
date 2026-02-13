"""
SignalCraft
Copyright (c) 2026 Chris Menendez.
All Rights Reserved.
See LICENSE for permitted use.
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ji_engine.utils.job_identity import job_identity, normalize_job_url

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass(frozen=True)
class HistoryRetentionResult:
    profile: str
    run_id: str
    run_pointer_path: str
    daily_pointer_path: str
    runs_kept: int
    runs_pruned: int
    daily_kept: int
    daily_pruned: int


@dataclass(frozen=True)
class HistoryRunArtifactsResult:
    profile: str
    run_id: str
    identity_map_path: str
    provenance_path: str
    identity_count: int


def _run_key(run_id: str) -> str:
    return run_id.strip()


def _run_day(run_id: str, run_timestamp: str) -> str:
    ts = (run_timestamp or "").strip()
    if len(ts) >= 10:
        day = ts[:10]
        if _DATE_RE.match(day):
            return day
    rid = (run_id or "").strip()
    if len(rid) >= 10:
        day = rid[:10]
        if _DATE_RE.match(day):
            return day
    raise ValueError(f"Unable to resolve YYYY-MM-DD from run_id={run_id!r} run_timestamp={run_timestamp!r}")


def _profile_root(history_dir: Path, profile: str) -> Path:
    return history_dir / profile


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON payload at {path} is not an object")
    return payload


def _iter_ranked_jobs(run_report: dict[str, Any], provider: str, profile: str) -> list[dict[str, Any]]:
    outputs_by_provider = run_report.get("outputs_by_provider")
    if not isinstance(outputs_by_provider, dict):
        return []
    provider_outputs = outputs_by_provider.get(provider)
    if not isinstance(provider_outputs, dict):
        return []
    profile_outputs = provider_outputs.get(profile)
    if not isinstance(profile_outputs, dict):
        return []
    ranked_json = profile_outputs.get("ranked_json")
    if not isinstance(ranked_json, dict):
        return []
    path = ranked_json.get("path")
    if not isinstance(path, str) or not path.strip():
        return []
    ranked_path = Path(path)
    if not ranked_path.exists():
        return []
    try:
        payload = json.loads(ranked_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(payload, list):
        return []
    rows: list[dict[str, Any]] = []
    for item in payload:
        if isinstance(item, dict):
            rows.append(dict(item))
    return rows


def _profile_provenance(run_report: dict[str, Any], providers: list[str]) -> dict[str, dict[str, Any]]:
    source = run_report.get("provenance_by_provider")
    if not isinstance(source, dict):
        return {}
    fields = (
        "scrape_mode",
        "snapshot_used",
        "parsed_job_count",
        "live_attempted",
        "live_result",
        "availability",
        "unavailable_reason",
        "rate_limit_min_delay_s",
        "rate_limit_jitter_s",
        "max_attempts",
        "backoff_base_s",
        "backoff_max_s",
        "backoff_jitter_s",
        "circuit_breaker_threshold",
        "circuit_breaker_cooldown_s",
        "robots_final_allowed",
        "robots_reason",
        "policy_snapshot",
    )
    output: dict[str, dict[str, Any]] = {}
    for provider in sorted(set(providers)):
        meta = source.get(provider)
        if not isinstance(meta, dict):
            continue
        output[provider] = {field: meta.get(field) for field in fields if field in meta}
    return output


def write_history_run_artifacts(
    *,
    history_dir: Path,
    run_id: str,
    profile: str,
    run_report_path: Path,
    written_at: str,
) -> HistoryRunArtifactsResult:
    run_report = _read_json(run_report_path)
    providers = [p for p in (run_report.get("providers") or []) if isinstance(p, str) and p.strip()]

    identities: dict[str, dict[str, Any]] = {}
    for provider in sorted(set(providers)):
        for job in _iter_ranked_jobs(run_report, provider, profile):
            job_id_raw = job.get("job_id")
            job_id = str(job_id_raw).strip() if isinstance(job_id_raw, str) and job_id_raw.strip() else ""
            if not job_id:
                job_id = job_identity(job, mode="provider")
            normalized_url = normalize_job_url(
                str(job.get("apply_url") or job.get("detail_url") or job.get("url") or "")
            )
            existing = identities.get(job_id)
            if existing is None:
                identities[job_id] = {
                    "job_id": job_id,
                    "providers": [provider],
                    "profiles": [profile],
                    "normalized_url": normalized_url or None,
                    "title": job.get("title"),
                    "location": job.get("location"),
                    "team": job.get("team"),
                    "jd_hash": job.get("jd_hash"),
                }
                continue
            providers_set = set(existing.get("providers", []))
            providers_set.add(provider)
            profiles_set = set(existing.get("profiles", []))
            profiles_set.add(profile)
            existing["providers"] = sorted(providers_set)
            existing["profiles"] = sorted(profiles_set)
            if not existing.get("normalized_url") and normalized_url:
                existing["normalized_url"] = normalized_url
            if not existing.get("title") and job.get("title"):
                existing["title"] = job.get("title")
            if not existing.get("location") and job.get("location"):
                existing["location"] = job.get("location")
            if not existing.get("team") and job.get("team"):
                existing["team"] = job.get("team")
            if not existing.get("jd_hash") and job.get("jd_hash"):
                existing["jd_hash"] = job.get("jd_hash")

    profile_root = _profile_root(history_dir, profile)
    run_dir = profile_root / "runs" / run_id
    identity_path = run_dir / "identity_map.json"
    provenance_path = run_dir / "provenance.json"

    identities_sorted = {job_id: identities[job_id] for job_id in sorted(identities)}
    _write_json(
        identity_path,
        {
            "schema_version": 1,
            "run_id": run_id,
            "profile": profile,
            "written_at": written_at,
            "run_report_path": run_report_path.as_posix(),
            "identity_count": len(identities_sorted),
            "identities_by_job_id": identities_sorted,
        },
    )

    _write_json(
        provenance_path,
        {
            "schema_version": 1,
            "run_id": run_id,
            "profile": profile,
            "written_at": written_at,
            "run_report_schema_version": run_report.get("run_report_schema_version"),
            "providers": sorted(set(providers)),
            "flags": {
                key: run_report.get("flags", {}).get(key)
                for key in (
                    "offline",
                    "snapshot_only",
                    "no_enrich",
                    "ai",
                    "ai_only",
                    "us_only",
                    "min_score",
                )
            },
            "selection_scrape_provenance": _profile_provenance(run_report, providers),
        },
    )

    return HistoryRunArtifactsResult(
        profile=profile,
        run_id=run_id,
        identity_map_path=identity_path.as_posix(),
        provenance_path=provenance_path.as_posix(),
        identity_count=len(identities_sorted),
    )


def _read_run_id_from_pointer(pointer_path: Path) -> str:
    try:
        payload = json.loads(pointer_path.read_text(encoding="utf-8"))
    except Exception:
        return pointer_path.parent.name
    run_id = payload.get("run_id")
    if isinstance(run_id, str) and run_id.strip():
        return run_id.strip()
    return pointer_path.parent.name


def _prune_run_pointers(runs_dir: Path, keep_runs: int) -> tuple[int, int]:
    entries: list[tuple[str, Path]] = []
    for child in sorted(runs_dir.iterdir(), key=lambda p: p.name):
        if not child.is_dir():
            continue
        pointer_path = child / "pointer.json"
        run_id = _read_run_id_from_pointer(pointer_path) if pointer_path.exists() else child.name
        entries.append((_run_key(run_id), child))
    entries.sort(key=lambda item: (item[0], item[1].name))
    keep = {path for _, path in entries[-keep_runs:]} if keep_runs > 0 else set()
    pruned = 0
    for _, path in entries:
        if path in keep:
            continue
        shutil.rmtree(path)
        pruned += 1
    return (len(keep), pruned)


def _prune_daily_pointers(daily_dir: Path, keep_days: int) -> tuple[int, int]:
    entries = [p for p in sorted(daily_dir.iterdir(), key=lambda p: p.name) if p.is_dir() and _DATE_RE.match(p.name)]
    keep = set(entries[-keep_days:]) if keep_days > 0 else set()
    pruned = 0
    for path in entries:
        if path in keep:
            continue
        shutil.rmtree(path)
        pruned += 1
    return (len(keep), pruned)


def update_history_retention(
    *,
    history_dir: Path,
    runs_dir: Path,
    profile: str,
    run_id: str,
    run_timestamp: str,
    keep_runs: int,
    keep_days: int,
    written_at: str,
) -> HistoryRetentionResult:
    if keep_runs < 1:
        raise ValueError(f"keep_runs must be >= 1 (got {keep_runs})")
    if keep_days < 1:
        raise ValueError(f"keep_days must be >= 1 (got {keep_days})")

    profile_root = _profile_root(history_dir, profile)
    profile_root.mkdir(parents=True, exist_ok=True)
    profile_runs = profile_root / "runs"
    profile_daily = profile_root / "daily"
    profile_runs.mkdir(parents=True, exist_ok=True)
    profile_daily.mkdir(parents=True, exist_ok=True)

    run_target = runs_dir / run_id.replace(":", "").replace("-", "").replace(".", "")
    run_pointer_dir = profile_runs / run_id
    run_pointer_path = run_pointer_dir / "pointer.json"
    run_payload = {
        "schema_version": 1,
        "profile": profile,
        "run_id": run_id,
        "run_dir": run_target.as_posix(),
        "written_at": written_at,
    }
    _write_json(run_pointer_path, run_payload)

    day = _run_day(run_id, run_timestamp)
    daily_pointer_path = profile_daily / day / "pointer.json"
    daily_payload = {
        "schema_version": 1,
        "profile": profile,
        "day": day,
        "run_id": run_id,
        "run_pointer": run_pointer_path.as_posix(),
        "written_at": written_at,
    }
    _write_json(daily_pointer_path, daily_payload)

    retention_path = profile_root / "retention.json"
    _write_json(
        retention_path,
        {
            "schema_version": 1,
            "profile": profile,
            "keep_runs": keep_runs,
            "keep_days": keep_days,
            "updated_at": written_at,
        },
    )

    runs_kept, runs_pruned = _prune_run_pointers(profile_runs, keep_runs)
    daily_kept, daily_pruned = _prune_daily_pointers(profile_daily, keep_days)

    return HistoryRetentionResult(
        profile=profile,
        run_id=run_id,
        run_pointer_path=run_pointer_path.as_posix(),
        daily_pointer_path=daily_pointer_path.as_posix(),
        runs_kept=runs_kept,
        runs_pruned=runs_pruned,
        daily_kept=daily_kept,
        daily_pruned=daily_pruned,
    )
