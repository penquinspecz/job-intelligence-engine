"""
SignalCraft
Copyright (c) 2026 Chris Menendez.
All Rights Reserved.
See LICENSE for permitted use.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .cache import (
    build_cache_entry,
    build_embedding_cache_key,
    embedding_cache_path,
    load_cache_entry,
    save_cache_entry,
)
from .core import (
    DEFAULT_SEMANTIC_MODEL_ID,
    EMBEDDING_BACKEND_VERSION,
    SEMANTIC_NORM_VERSION,
    embed_texts,
    normalize_text_for_embedding,
)


def _sanitize_run_id(run_id: str) -> str:
    return run_id.replace(":", "").replace("-", "").replace(".", "")


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _canonical_profile_text(profile_data: Any) -> str:
    return json.dumps(profile_data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_ranked_jobs(path: Path) -> List[Dict[str, Any]]:
    try:
        payload = _load_json(path)
    except Exception:
        return []
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


def _job_id(job: Dict[str, Any]) -> str:
    job_id = str(job.get("job_id") or "").strip()
    if job_id:
        return job_id
    fallback = str(job.get("apply_url") or job.get("detail_url") or job.get("title") or "").strip()
    if fallback:
        return f"missing:{_sha256_text(fallback)[:16]}"
    return "missing:unknown"


def _job_embedding_text(job: Dict[str, Any]) -> str:
    fields = (
        "title",
        "location",
        "team",
        "company",
        "apply_url",
        "detail_url",
        "summary",
        "description",
        "raw_text",
    )
    values = [str(job.get(field) or "") for field in fields]
    return " ".join(values)


def _collect_ranked_records(
    provider_outputs: Dict[str, Dict[str, Dict[str, Dict[str, Optional[str]]]]],
    max_jobs: int,
) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    for provider in sorted(provider_outputs.keys()):
        by_profile = provider_outputs.get(provider) or {}
        for profile in sorted(by_profile.keys()):
            ranked_meta = (by_profile.get(profile) or {}).get("ranked_json") or {}
            ranked_path_raw = ranked_meta.get("path")
            if not ranked_path_raw:
                continue
            ranked_path = Path(ranked_path_raw)
            jobs = _load_ranked_jobs(ranked_path)
            jobs.sort(
                key=lambda job: (
                    _job_id(job),
                    str(job.get("apply_url") or "").lower(),
                    str(job.get("title") or "").lower(),
                )
            )
            for job in jobs:
                records.append({"provider": provider, "profile": profile, "job": job})
                if len(records) >= max_jobs:
                    return records
    return records


def _write_summary(summary_path: Path, payload: Dict[str, Any]) -> None:
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def run_semantic_sidecar(
    *,
    run_id: str,
    provider_outputs: Dict[str, Dict[str, Dict[str, Dict[str, Optional[str]]]]],
    state_dir: Path,
    run_metadata_dir: Path,
    candidate_profile_path: Path,
    enabled: bool,
    model_id: str,
    max_jobs: int,
    semantic_threshold: float = 0.72,
) -> Tuple[Dict[str, Any], Path]:
    run_dir = run_metadata_dir / _sanitize_run_id(run_id)
    summary_path = run_dir / "semantic" / "semantic_summary.json"
    summary: Dict[str, Any] = {
        "enabled": bool(enabled),
        "model_id": model_id,
        "embedding_backend_version": EMBEDDING_BACKEND_VERSION,
        "norm_version": SEMANTIC_NORM_VERSION,
        "normalized_text_hash": None,
        "embedding_cache_key": None,
        "cache_hit_counts": {"hit": 0, "miss": 0, "write": 0},
        "embedded_job_count": 0,
        "entries": [],
        "skipped_reason": None,
    }

    if not enabled:
        summary["skipped_reason"] = "semantic_disabled"
        _write_summary(summary_path, summary)
        return summary, summary_path

    if model_id != DEFAULT_SEMANTIC_MODEL_ID:
        summary["skipped_reason"] = f"unsupported_model_id:{model_id}"
        _write_summary(summary_path, summary)
        return summary, summary_path

    if max_jobs < 1:
        summary["skipped_reason"] = "invalid_max_jobs"
        _write_summary(summary_path, summary)
        return summary, summary_path

    if not candidate_profile_path.exists():
        summary["skipped_reason"] = "candidate_profile_missing"
        _write_summary(summary_path, summary)
        return summary, summary_path

    try:
        profile_data = _load_json(candidate_profile_path)
    except Exception:
        summary["skipped_reason"] = "candidate_profile_invalid_json"
        _write_summary(summary_path, summary)
        return summary, summary_path

    profile_text = normalize_text_for_embedding(_canonical_profile_text(profile_data))
    candidate_profile_hash = _sha256_text(profile_text)
    profile_cache_key = build_embedding_cache_key(
        job_id="__candidate_profile__",
        job_content_hash=candidate_profile_hash,
        candidate_profile_hash=candidate_profile_hash,
        semantic_threshold=semantic_threshold,
    )
    summary["normalized_text_hash"] = candidate_profile_hash
    summary["embedding_cache_key"] = profile_cache_key

    records = _collect_ranked_records(provider_outputs, max_jobs)
    if not records:
        summary["skipped_reason"] = "no_ranked_jobs"
        _write_summary(summary_path, summary)
        return summary, summary_path

    misses: List[Dict[str, Any]] = []
    for record in records:
        provider = record["provider"]
        profile = record["profile"]
        job = record["job"]
        job_id = _job_id(job)
        job_text = normalize_text_for_embedding(_job_embedding_text(job))
        job_content_hash = _sha256_text(job_text)
        cache_key = build_embedding_cache_key(
            job_id=job_id,
            job_content_hash=job_content_hash,
            candidate_profile_hash=candidate_profile_hash,
            semantic_threshold=semantic_threshold,
        )
        cache_path = embedding_cache_path(state_dir, model_id, cache_key)
        cache_entry = load_cache_entry(cache_path)

        cache_hit = False
        if isinstance(cache_entry, dict):
            input_hashes = cache_entry.get("input_hashes") if isinstance(cache_entry.get("input_hashes"), dict) else {}
            cache_hit = (
                cache_entry.get("model_id") == model_id
                and input_hashes.get("job_id") == job_id
                and input_hashes.get("job_content_hash") == job_content_hash
                and input_hashes.get("candidate_profile_hash") == candidate_profile_hash
                and input_hashes.get("norm_version") == SEMANTIC_NORM_VERSION
                and input_hashes.get("semantic_threshold") == f"{round(float(semantic_threshold), 6):.6f}"
                and isinstance(cache_entry.get("vector"), list)
            )

        summary["entries"].append(
            {
                "provider": provider,
                "profile": profile,
                "job_id": job_id,
                "job_content_hash": job_content_hash,
                "candidate_profile_hash": candidate_profile_hash,
                "cache_key": cache_key,
                "cache_hit": cache_hit,
            }
        )
        if cache_hit:
            summary["cache_hit_counts"]["hit"] += 1
        else:
            summary["cache_hit_counts"]["miss"] += 1
            misses.append(
                {
                    "cache_key": cache_key,
                    "cache_path": cache_path,
                    "job_id": job_id,
                    "job_content_hash": job_content_hash,
                    "candidate_profile_hash": candidate_profile_hash,
                    "text": job_text,
                }
            )

    if misses:
        vectors = embed_texts([item["text"] for item in misses], model_id)
        for miss, vector in zip(misses, vectors, strict=True):
            entry = build_cache_entry(
                model_id=model_id,
                job_id=miss["job_id"],
                job_content_hash=miss["job_content_hash"],
                candidate_profile_hash=miss["candidate_profile_hash"],
                vector=vector,
                cache_key=miss["cache_key"],
                semantic_threshold=semantic_threshold,
            )
            save_cache_entry(miss["cache_path"], entry)
            summary["cache_hit_counts"]["write"] += 1

    summary["embedded_job_count"] = len(summary["entries"])
    _write_summary(summary_path, summary)
    return summary, summary_path


def semantic_score_artifact_path(
    *,
    run_id: str,
    provider: str,
    profile: str,
    run_metadata_dir: Path,
) -> Path:
    run_dir = run_metadata_dir / _sanitize_run_id(run_id)
    return run_dir / "semantic" / f"scores_{provider}_{profile}.json"


def finalize_semantic_artifacts(
    *,
    run_id: str,
    run_metadata_dir: Path,
    enabled: bool,
    model_id: str,
    policy: Dict[str, Any],
) -> tuple[Dict[str, Any], Path, Path]:
    run_dir = run_metadata_dir / _sanitize_run_id(run_id)
    semantic_dir = run_dir / "semantic"
    scores_path = semantic_dir / "semantic_scores.json"
    summary_path = semantic_dir / "semantic_summary.json"
    semantic_dir.mkdir(parents=True, exist_ok=True)

    per_profile_paths = sorted(semantic_dir.glob("scores_*.json"), key=lambda p: p.name)
    entries: List[Dict[str, Any]] = []
    cache_totals = {"hit": 0, "miss": 0, "write": 0, "profile_hit": 0, "profile_miss": 0}
    skipped: List[str] = []
    normalized_text_hash: Optional[str] = None
    embedding_cache_key: Optional[str] = None
    embedding_backend_version = EMBEDDING_BACKEND_VERSION

    for path in per_profile_paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            skipped.append(f"invalid_json:{path.name}")
            continue
        if not isinstance(payload, dict):
            skipped.append(f"invalid_shape:{path.name}")
            continue
        for key in cache_totals:
            try:
                cache_totals[key] += int(((payload.get("cache_hit_counts") or {}).get(key, 0)) or 0)
            except Exception:
                pass
        reason = payload.get("skipped_reason")
        if reason:
            skipped.append(str(reason))
        candidate_hash = payload.get("normalized_text_hash")
        if normalized_text_hash is None and isinstance(candidate_hash, str) and candidate_hash:
            normalized_text_hash = candidate_hash
        candidate_cache_key = payload.get("embedding_cache_key")
        if embedding_cache_key is None and isinstance(candidate_cache_key, str) and candidate_cache_key:
            embedding_cache_key = candidate_cache_key
        backend_version = payload.get("embedding_backend_version")
        if isinstance(backend_version, str) and backend_version:
            embedding_backend_version = backend_version
        payload_entries = payload.get("entries")
        if isinstance(payload_entries, list):
            for item in payload_entries:
                if isinstance(item, dict):
                    entries.append(item)

    entries.sort(
        key=lambda item: (
            str(item.get("provider") or ""),
            str(item.get("profile") or ""),
            str(item.get("job_id") or ""),
        )
    )
    scores_path.write_text(json.dumps(entries, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    summary: Dict[str, Any] = {
        "enabled": bool(enabled),
        "model_id": model_id,
        "embedding_backend_version": embedding_backend_version,
        "policy": dict(policy),
        "normalized_text_hash": normalized_text_hash,
        "embedding_cache_key": embedding_cache_key,
        "cache_hit_counts": cache_totals,
        "embedded_job_count": len(entries),
        "skipped_reason": None,
    }
    if not enabled:
        summary["skipped_reason"] = "semantic_disabled"
    elif not per_profile_paths:
        summary["skipped_reason"] = "no_semantic_score_artifacts"
    elif skipped and not entries:
        summary["skipped_reason"] = skipped[0]
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary, summary_path, scores_path
