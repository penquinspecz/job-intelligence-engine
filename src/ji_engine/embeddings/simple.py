from __future__ import annotations

import json
import math
import re
import hashlib
from pathlib import Path
from typing import Any, Dict, Iterable, List


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
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def load_cache(path: Path) -> Dict[str, Dict[str, List[float]]]:
    if not path.exists():
        return {"profile": {}, "job": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"profile": {}, "job": {}}
        data.setdefault("profile", {})
        data.setdefault("job", {})
        return data
    except Exception:
        return {"profile": {}, "job": {}}


def save_cache(path: Path, cache: Dict[str, Dict[str, List[float]]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


__all__ = [
    "hash_embed",
    "cosine_similarity",
    "load_cache",
    "save_cache",
    "text_hash",
    "build_profile_text",
]

