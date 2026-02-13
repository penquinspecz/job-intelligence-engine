"""
SignalCraft
Copyright (c) 2026 Chris Menendez.
All Rights Reserved.
See LICENSE for permitted use.
"""

from .boost import SemanticPolicy, apply_bounded_semantic_boost
from .cache import (
    build_cache_entry,
    build_embedding_cache_key,
    embedding_cache_dir,
    embedding_cache_path,
    load_cache_entry,
    save_cache_entry,
)
from .core import (
    DEFAULT_SEMANTIC_MODEL_ID,
    EMBEDDING_BACKEND_VERSION,
    SEMANTIC_NORM_VERSION,
    DeterministicHashEmbeddingBackend,
    cosine_similarity,
    embed_texts,
    normalize_text_for_embedding,
)
from .step import finalize_semantic_artifacts, run_semantic_sidecar, semantic_score_artifact_path

__all__ = [
    "DEFAULT_SEMANTIC_MODEL_ID",
    "EMBEDDING_BACKEND_VERSION",
    "SEMANTIC_NORM_VERSION",
    "DeterministicHashEmbeddingBackend",
    "normalize_text_for_embedding",
    "embed_texts",
    "cosine_similarity",
    "embedding_cache_dir",
    "embedding_cache_path",
    "build_embedding_cache_key",
    "build_cache_entry",
    "load_cache_entry",
    "save_cache_entry",
    "run_semantic_sidecar",
    "semantic_score_artifact_path",
    "finalize_semantic_artifacts",
    "SemanticPolicy",
    "apply_bounded_semantic_boost",
]
