from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .core import SEMANTIC_NORM_VERSION


def _safe_model_id(model_id: str) -> str:
    value = (model_id or "").strip()
    if not value:
        return "unknown-model"
    return "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in value)


def embedding_cache_dir(state_dir: Path, model_id: str) -> Path:
    return state_dir / "embeddings" / _safe_model_id(model_id)


def embedding_cache_path(state_dir: Path, model_id: str, cache_key: str) -> Path:
    return embedding_cache_dir(state_dir, model_id) / f"{cache_key}.json"


def build_embedding_cache_key(
    *,
    job_id: str,
    job_content_hash: str,
    candidate_profile_hash: str,
    norm_version: str = SEMANTIC_NORM_VERSION,
) -> str:
    payload = {
        "job_id": job_id,
        "job_content_hash": job_content_hash,
        "candidate_profile_hash": candidate_profile_hash,
        "norm_version": norm_version,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _deterministic_created_at(cache_key: str) -> str:
    seed = int(cache_key[:8], 16)
    dt = datetime(2020, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=seed % (365 * 24 * 3600))
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def build_cache_entry(
    *,
    model_id: str,
    job_id: str,
    job_content_hash: str,
    candidate_profile_hash: str,
    vector: List[float],
    norm_version: str = SEMANTIC_NORM_VERSION,
    cache_key: str,
) -> Dict[str, Any]:
    return {
        "model_id": model_id,
        "created_at": _deterministic_created_at(cache_key),
        "input_hashes": {
            "job_id": job_id,
            "job_content_hash": job_content_hash,
            "candidate_profile_hash": candidate_profile_hash,
            "norm_version": norm_version,
        },
        "vector": [round(float(v), 8) for v in vector],
    }


def load_cache_entry(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    if not isinstance(data.get("input_hashes"), dict):
        return None
    if not isinstance(data.get("vector"), list):
        return None
    return data


def save_cache_entry(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)
