from __future__ import annotations

from ji_engine.semantic.core import (
    DEFAULT_SEMANTIC_MODEL_ID,
    DeterministicHashEmbeddingBackend,
    cosine_similarity,
    embed_texts,
    normalize_text_for_embedding,
)


def test_normalize_text_for_embedding_is_deterministic() -> None:
    left = "  Senior,   ML ENGINEER!!!  (Remote-US) "
    right = "senior ml engineer remote us"
    mixed = "SENIOR ml\nEngineer\tremote   US"

    assert normalize_text_for_embedding(left) == "senior ml engineer remote us"
    assert normalize_text_for_embedding(right) == "senior ml engineer remote us"
    assert normalize_text_for_embedding(mixed) == "senior ml engineer remote us"


def test_hash_backend_vectors_are_stable() -> None:
    backend = DeterministicHashEmbeddingBackend(dim=16)
    text = "Deterministic Semantic Vector"
    first = backend.embed_texts([text], DEFAULT_SEMANTIC_MODEL_ID)[0]
    second = backend.embed_texts([text], DEFAULT_SEMANTIC_MODEL_ID)[0]

    assert first == second
    assert len(first) == 16


def test_embed_texts_default_backend_is_deterministic() -> None:
    texts = ["alpha role", "beta role"]
    first = embed_texts(texts, DEFAULT_SEMANTIC_MODEL_ID)
    second = embed_texts(texts, DEFAULT_SEMANTIC_MODEL_ID)
    assert first == second


def test_cosine_similarity_rounding_is_deterministic() -> None:
    vec_a = [0.1, 0.2, 0.3]
    vec_b = [0.2, 0.1, 0.4]
    assert cosine_similarity(vec_a, vec_b) == cosine_similarity(vec_a, vec_b)
