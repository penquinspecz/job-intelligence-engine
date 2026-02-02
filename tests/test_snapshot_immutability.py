from __future__ import annotations

import json
from pathlib import Path

from ji_engine.utils.verification import compute_sha256_bytes


def test_pinned_snapshots_immutable() -> None:
    manifest_path = Path("tests/fixtures/golden/snapshot_bytes.manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    for rel_path, expected in manifest.items():
        path = Path(rel_path)
        assert path.exists(), f"Snapshot missing: {path}"
        data = path.read_bytes()
        actual_sha, actual_bytes = compute_sha256_bytes(data), len(data)
        expected_sha = expected.get("sha256")
        expected_bytes = expected.get("bytes")
        if actual_sha != expected_sha or actual_bytes != expected_bytes:
            raise AssertionError(
                "Pinned snapshot bytes changed.\n"
                f"Path: {path}\n"
                f"Expected sha256: {expected_sha}\n"
                f"Actual sha256:   {actual_sha}\n"
                f"Expected bytes: {expected_bytes}\n"
                f"Actual bytes:   {actual_bytes}\n"
                "Restore snapshots to HEAD or re-run the snapshot refresh workflow intentionally."
            )
