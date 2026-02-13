from __future__ import annotations

import hashlib
import json
from pathlib import Path


def test_ci_required_contract_files_exist() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    required = [
        repo_root / "docs" / "DETERMINISM_CONTRACT.md",
        repo_root / "config" / "scoring.v1.json",
        repo_root / "schemas" / "run_health.schema.v1.json",
    ]
    missing = [str(path) for path in required if not path.exists()]
    assert not missing, f"missing deterministic CI parity files: {missing}"


def test_hash_normalization_uses_explicit_utf8_encoding() -> None:
    payload = {"a": "alpha", "z": "zeta", "n": 3}
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    # Fixed fixture guard: this digest must remain stable across CI/local runtimes.
    assert digest == "779c9f4a4f010f40b07a26f94fbb6f1e812e7e5f5f48f8feb8da121c66e7c927"
