from __future__ import annotations

import hashlib
import math
import re
from typing import List, Protocol, Sequence

DEFAULT_SEMANTIC_MODEL_ID = "deterministic-hash-v1"
SEMANTIC_NORM_VERSION = "semantic_norm_v1"
_TOKEN_RE = re.compile(r"[a-z0-9]+")


def normalize_text_for_embedding(text: str) -> str:
    tokens = _TOKEN_RE.findall((text or "").lower())
    return " ".join(tokens)


class EmbeddingBackend(Protocol):
    def embed_texts(self, texts: Sequence[str], model_id: str) -> List[List[float]]: ...


class DeterministicHashEmbeddingBackend:
    """Offline deterministic backend: normalized text -> stable hash vector."""

    def __init__(self, *, dim: int = 24) -> None:
        if dim < 1:
            raise ValueError("dim must be >= 1")
        self.dim = dim

    def _embed_one(self, text: str) -> List[float]:
        normalized = normalize_text_for_embedding(text)
        digest = hashlib.sha256(normalized.encode("utf-8")).digest()
        vector: List[float] = []
        for i in range(self.dim):
            offset = (i * 2) % len(digest)
            chunk = digest[offset : offset + 2]
            if len(chunk) < 2:
                chunk = (chunk + digest)[:2]
            value = int.from_bytes(chunk, byteorder="big", signed=False) / 65535.0
            # Stable bounded float representation for deterministic JSON serialization.
            vector.append(round((value * 2.0) - 1.0, 8))
        return vector

    def embed_texts(self, texts: Sequence[str], model_id: str) -> List[List[float]]:
        if model_id != DEFAULT_SEMANTIC_MODEL_ID:
            raise ValueError(f"unsupported semantic model_id '{model_id}'")
        return [self._embed_one(text) for text in texts]


def embed_texts(
    texts: Sequence[str],
    model_id: str,
    *,
    backend: EmbeddingBackend | None = None,
) -> List[List[float]]:
    backend_impl = backend or DeterministicHashEmbeddingBackend()
    return backend_impl.embed_texts(texts, model_id)


def cosine_similarity(vec_a: Sequence[float], vec_b: Sequence[float]) -> float:
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    dot = sum(float(a) * float(b) for a, b in zip(vec_a, vec_b, strict=True))
    norm_a = math.sqrt(sum(float(a) * float(a) for a in vec_a))
    norm_b = math.sqrt(sum(float(b) * float(b) for b in vec_b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return round(dot / (norm_a * norm_b), 8)
