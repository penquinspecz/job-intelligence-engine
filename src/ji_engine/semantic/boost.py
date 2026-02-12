from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

from .cache import (
    build_cache_entry,
    build_embedding_cache_key,
    embedding_cache_path,
    load_cache_entry,
    save_cache_entry,
)
from .core import (
    DEFAULT_SEMANTIC_MODEL_ID,
    SEMANTIC_NORM_VERSION,
    cosine_similarity,
    embed_texts,
    normalize_text_for_embedding,
)


@dataclass(frozen=True)
class SemanticPolicy:
    enabled: bool = False
    model_id: str = DEFAULT_SEMANTIC_MODEL_ID
    max_jobs: int = 200
    top_k: int = 50
    max_boost: float = 5.0
    min_similarity: float = 0.72


def _clamp(value: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, value))


def _profile_text(profile_payload: Any) -> str:
    return normalize_text_for_embedding(
        json.dumps(profile_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    )


def _job_text(job: Dict[str, Any]) -> str:
    fields = [
        str(job.get("title") or ""),
        str(job.get("location") or job.get("locationName") or ""),
        str(job.get("team") or ""),
        str(job.get("department") or job.get("departmentName") or ""),
        str(job.get("summary") or ""),
        str(job.get("description") or ""),
        str(job.get("jd_text") or ""),
    ]
    return normalize_text_for_embedding(" ".join(fields))


def _sha256(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _job_id(job: Dict[str, Any]) -> str:
    value = str(job.get("job_id") or "").strip()
    if value:
        return value
    fallback = str(job.get("apply_url") or job.get("detail_url") or job.get("title") or "").strip()
    return fallback or "missing:unknown"


def _ranking_key(job: Dict[str, Any]) -> Tuple[int, str, str, str]:
    score = int(job.get("score", 0) or 0)
    provider = str(job.get("provider") or job.get("source") or "").lower()
    profile = str(job.get("profile") or job.get("scoring_profile") or "").lower()
    stable_id = _job_id(job).lower()
    return (-score, provider, profile, stable_id)


def _semantic_boost(similarity: float, *, min_similarity: float, max_boost: float) -> float:
    sim = round(float(similarity), 6)
    if sim < min_similarity:
        return 0.0
    if min_similarity >= 1.0:
        return 0.0
    span = 1.0 - min_similarity
    raw = ((sim - min_similarity) / span) * max_boost
    return round(max(0.0, min(max_boost, raw)), 6)


def _resolve_profile_vector(
    *,
    profile_payload: Any,
    state_dir: Path,
    model_id: str,
) -> Tuple[List[float], str, bool]:
    profile_text = _profile_text(profile_payload)
    profile_hash = _sha256(profile_text)
    cache_key = build_embedding_cache_key(
        job_id="__candidate_profile__",
        job_content_hash=profile_hash,
        candidate_profile_hash=profile_hash,
    )
    cache_path = embedding_cache_path(state_dir, model_id, cache_key)
    entry = load_cache_entry(cache_path)
    if isinstance(entry, dict) and isinstance(entry.get("vector"), list):
        hashes = entry.get("input_hashes") if isinstance(entry.get("input_hashes"), dict) else {}
        if (
            entry.get("model_id") == model_id
            and hashes.get("job_id") == "__candidate_profile__"
            and hashes.get("job_content_hash") == profile_hash
            and hashes.get("candidate_profile_hash") == profile_hash
            and hashes.get("norm_version") == SEMANTIC_NORM_VERSION
        ):
            return [float(v) for v in entry["vector"]], profile_hash, True

    vector = embed_texts([profile_text], model_id)[0]
    save_cache_entry(
        cache_path,
        build_cache_entry(
            model_id=model_id,
            job_id="__candidate_profile__",
            job_content_hash=profile_hash,
            candidate_profile_hash=profile_hash,
            vector=vector,
            cache_key=cache_key,
        ),
    )
    return vector, profile_hash, False


def apply_bounded_semantic_boost(
    *,
    scored_jobs: List[Dict[str, Any]],
    profile_payload: Any,
    state_dir: Path,
    policy: SemanticPolicy,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    if not policy.enabled:
        return scored_jobs, {
            "enabled": False,
            "model_id": policy.model_id,
            "policy": {
                "max_boost": policy.max_boost,
                "min_similarity": policy.min_similarity,
                "top_k": policy.top_k,
                "max_jobs": policy.max_jobs,
            },
            "cache_hit_counts": {"hit": 0, "miss": 0, "write": 0, "profile_hit": 0, "profile_miss": 0},
            "entries": [],
            "skipped_reason": "semantic_disabled",
        }

    if policy.model_id != DEFAULT_SEMANTIC_MODEL_ID:
        return scored_jobs, {
            "enabled": True,
            "model_id": policy.model_id,
            "policy": {
                "max_boost": policy.max_boost,
                "min_similarity": policy.min_similarity,
                "top_k": policy.top_k,
                "max_jobs": policy.max_jobs,
            },
            "cache_hit_counts": {"hit": 0, "miss": 0, "write": 0, "profile_hit": 0, "profile_miss": 0},
            "entries": [],
            "skipped_reason": f"unsupported_model_id:{policy.model_id}",
        }

    ranked = sorted([dict(job) for job in scored_jobs], key=_ranking_key)
    evaluate_n = min(len(ranked), max(1, policy.max_jobs), max(1, policy.top_k))

    profile_vec, profile_hash, profile_hit = _resolve_profile_vector(
        profile_payload=profile_payload,
        state_dir=state_dir,
        model_id=policy.model_id,
    )
    cache_counts = {
        "hit": 0,
        "miss": 0,
        "write": 0,
        "profile_hit": int(profile_hit),
        "profile_miss": int(not profile_hit),
    }

    evidences: List[Dict[str, Any]] = []
    misses: List[Tuple[int, str, str, str, Path, Dict[str, Any], str]] = []

    for idx, job in enumerate(ranked):
        base_score = int(job.get("score", 0) or 0)
        jid = _job_id(job)
        if idx >= evaluate_n:
            evidences.append(
                {
                    "job_id": jid,
                    "base_score": base_score,
                    "similarity": None,
                    "semantic_boost": 0.0,
                    "final_score": base_score,
                    "reasons": ["not_in_top_k"],
                }
            )
            continue

        job_text = _job_text(job)
        job_hash = _sha256(job_text)
        cache_key = build_embedding_cache_key(
            job_id=jid,
            job_content_hash=job_hash,
            candidate_profile_hash=profile_hash,
        )
        cache_path = embedding_cache_path(state_dir, policy.model_id, cache_key)
        cache_entry = load_cache_entry(cache_path)
        vector: Sequence[float] | None = None
        if isinstance(cache_entry, dict) and isinstance(cache_entry.get("vector"), list):
            input_hashes = cache_entry.get("input_hashes") if isinstance(cache_entry.get("input_hashes"), dict) else {}
            if (
                cache_entry.get("model_id") == policy.model_id
                and input_hashes.get("job_id") == jid
                and input_hashes.get("job_content_hash") == job_hash
                and input_hashes.get("candidate_profile_hash") == profile_hash
                and input_hashes.get("norm_version") == SEMANTIC_NORM_VERSION
            ):
                vector = [float(v) for v in cache_entry["vector"]]
                cache_counts["hit"] += 1
        if vector is None:
            cache_counts["miss"] += 1
            misses.append((idx, jid, job_hash, cache_key, cache_path, job, job_text))
            continue

        sim = round(cosine_similarity(profile_vec, vector), 6)
        boost = _semantic_boost(sim, min_similarity=policy.min_similarity, max_boost=policy.max_boost)
        final_score = _clamp(int(round(base_score + boost)), 0, 100)
        reasons = ["boost_applied"] if boost > 0 else ["below_min_similarity"]
        job["similarity"] = sim
        job["semantic_boost"] = boost
        job["score"] = final_score
        job["final_score"] = final_score
        ranked[idx] = job
        evidences.append(
            {
                "job_id": jid,
                "base_score": base_score,
                "similarity": sim,
                "semantic_boost": boost,
                "final_score": final_score,
                "reasons": reasons,
            }
        )

    if misses:
        vectors = embed_texts([item[6] for item in misses], policy.model_id)
        for miss, vector in zip(misses, vectors, strict=True):
            idx, jid, job_hash, cache_key, cache_path, job, _ = miss
            save_cache_entry(
                cache_path,
                build_cache_entry(
                    model_id=policy.model_id,
                    job_id=jid,
                    job_content_hash=job_hash,
                    candidate_profile_hash=profile_hash,
                    vector=list(vector),
                    cache_key=cache_key,
                ),
            )
            cache_counts["write"] += 1
            sim = round(cosine_similarity(profile_vec, vector), 6)
            boost = _semantic_boost(sim, min_similarity=policy.min_similarity, max_boost=policy.max_boost)
            base_score = int(job.get("score", 0) or 0)
            final_score = _clamp(int(round(base_score + boost)), 0, 100)
            reasons = ["boost_applied"] if boost > 0 else ["below_min_similarity"]
            job["similarity"] = sim
            job["semantic_boost"] = boost
            job["score"] = final_score
            job["final_score"] = final_score
            ranked[idx] = job
            evidences.append(
                {
                    "job_id": jid,
                    "base_score": base_score,
                    "similarity": sim,
                    "semantic_boost": boost,
                    "final_score": final_score,
                    "reasons": reasons,
                }
            )

    ranked.sort(key=_ranking_key)
    evidences.sort(key=lambda item: str(item.get("job_id") or ""))
    evidence_payload = {
        "enabled": True,
        "model_id": policy.model_id,
        "policy": {
            "max_boost": policy.max_boost,
            "min_similarity": policy.min_similarity,
            "top_k": policy.top_k,
            "max_jobs": policy.max_jobs,
        },
        "cache_hit_counts": cache_counts,
        "entries": evidences,
        "skipped_reason": None,
    }
    return ranked, evidence_payload
