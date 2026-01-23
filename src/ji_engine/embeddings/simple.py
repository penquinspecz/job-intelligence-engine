from __future__ import annotations

import hashlib
import json
import math
import os
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List

from ji_engine.utils.compat import zip_pairs

TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> Iterable[str]:
    for tok in TOKEN_RE.findall(text.lower()):
        yield tok


def text_hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def build_profile_text(profile: Any) -> str:
    if hasattr(profile, "model_dump"):
        data = profile.model_dump()
    elif hasattr(profile, "dict"):
        data = profile.dict()
    else:
        data = profile

    parts: List[str] = []

    def _walk(val: Any) -> None:
        if isinstance(val, dict):
            for v in val.values():
                _walk(v)
        elif isinstance(val, list):
            for v in val:
                _walk(v)
        elif isinstance(val, (str, int, float)):
            parts.append(str(val))

    _walk(data)
    return " ".join(parts)


def hash_embed(text: str, dim: int = 256) -> List[float]:
    """
    Simple hashing-based embedding with fixed dimension.
    """
    vec = [0.0] * dim
    for tok in tokenize(text or ""):
        h = int(hashlib.md5(tok.encode("utf-8")).hexdigest(), 16)
        idx = h % dim
        vec[idx] += 1.0
    return vec


def cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    dot = sum(a * b for a, b in zip_pairs(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def load_cache(path: Path) -> Dict[str, Dict[str, List[float]]]:
    bucket = os.getenv("JOBINTEL_S3_BUCKET", "").strip()
    prefix = os.getenv("JOBINTEL_S3_PREFIX", "").strip("/")

    def _empty() -> Dict[str, Dict[str, List[float]]]:
        return {"profile": {}, "job": {}}

    def _normalize(data: Any) -> Dict[str, Dict[str, List[float]]]:
        if not isinstance(data, dict):
            return _empty()
        data.setdefault("profile", {})
        data.setdefault("job", {})
        return data  # type: ignore[return-value]

    if bucket:
        try:
            import boto3  # type: ignore

            region = os.getenv("AWS_REGION") or None
            client = boto3.client("s3", region_name=region)
            key_prefix = f"{prefix}/" if prefix else ""
            key = f"{key_prefix}state/{path.name}"
            obj = client.get_object(Bucket=bucket, Key=key)
            return _normalize(json.loads(obj["Body"].read().decode("utf-8")))
        except Exception:
            return _empty()

    if not path.exists():
        return _empty()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return _normalize(data)
    except Exception:
        return _empty()


def save_cache(path: Path, cache: Dict[str, Dict[str, List[float]]]) -> None:
    bucket = os.getenv("JOBINTEL_S3_BUCKET", "").strip()
    prefix = os.getenv("JOBINTEL_S3_PREFIX", "").strip("/")

    data = json.dumps(cache, ensure_ascii=False, indent=2).encode("utf-8")

    if bucket:
        try:
            import boto3  # type: ignore

            region = os.getenv("AWS_REGION") or None
            client = boto3.client("s3", region_name=region)
            key_prefix = f"{prefix}/" if prefix else ""
            key = f"{key_prefix}state/{path.name}"
            client.put_object(Bucket=bucket, Key=key, Body=data)
            return
        except Exception:
            # fall back to local write if S3 fails
            pass

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data.decode("utf-8"), encoding="utf-8")


__all__ = [
    "hash_embed",
    "cosine_similarity",
    "load_cache",
    "save_cache",
    "text_hash",
    "build_profile_text",
]
