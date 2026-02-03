from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Dict, List, Tuple


def compute_sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def compute_sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8192), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _rel_path_for_logical_key(base_dir: Path, logical_key: str, path: Path) -> str:
    if path.is_absolute():
        try:
            return path.relative_to(base_dir).as_posix()
        except ValueError:
            pass
    return path.name


def build_verifiable_artifacts(base_dir: Path, artifacts: Dict[str, Path]) -> Dict[str, Dict[str, str]]:
    payload: Dict[str, Dict[str, str]] = {}
    for logical_key, path in artifacts.items():
        if not path.exists():
            continue
        rel_path = _rel_path_for_logical_key(base_dir, logical_key, path)
        payload[logical_key] = {
            "path": rel_path,
            "sha256": compute_sha256_file(path),
            "bytes": path.stat().st_size,
            "hash_algo": "sha256",
        }
    return payload


def verify_verifiable_artifacts(
    base_dir: Path, verifiable_artifacts: Dict[str, Dict[str, str]]
) -> Tuple[bool, List[Dict[str, str]]]:
    mismatches: List[Dict[str, str]] = []
    for logical_key, meta in verifiable_artifacts.items():
        if not isinstance(meta, dict):
            mismatches.append({"label": logical_key, "expected": None, "actual": None, "reason": "invalid_metadata"})
            continue
        expected = meta.get("sha256")
        path_str = meta.get("path")
        if not expected or not path_str:
            mismatches.append(
                {"label": logical_key, "expected": expected, "actual": None, "reason": "missing_path_or_hash"}
            )
            continue
        path = Path(path_str)
        if not path.is_absolute():
            path = base_dir / path
        if not path.exists():
            mismatches.append({"label": logical_key, "expected": expected, "actual": None, "reason": "missing_file"})
            continue
        actual = compute_sha256_file(path)
        if actual != expected:
            mismatches.append({"label": logical_key, "expected": expected, "actual": actual, "reason": "mismatch"})
    return len(mismatches) == 0, mismatches
