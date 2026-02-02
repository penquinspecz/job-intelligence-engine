#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

from ji_engine.utils.verification import compute_sha256_bytes


def main() -> int:
    manifest_path = Path("tests/fixtures/golden/snapshot_bytes.manifest.json")
    if not manifest_path.exists():
        print(f"Missing manifest: {manifest_path}")
        return 2

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    mismatches: list[str] = []

    for rel_path, expected in manifest.items():
        path = Path(rel_path)
        if not path.exists():
            mismatches.append(f"Missing snapshot: {path}")
            continue
        data = path.read_bytes()
        actual_sha, actual_bytes = compute_sha256_bytes(data), len(data)
        expected_sha = expected.get("sha256")
        expected_bytes = expected.get("bytes")
        print(f"{path}: sha256={actual_sha} bytes={actual_bytes}")
        if actual_sha != expected_sha or actual_bytes != expected_bytes:
            mismatches.append(
                "\n".join(
                    [
                        f"Path: {path}",
                        f"Expected sha256: {expected_sha}",
                        f"Actual sha256:   {actual_sha}",
                        f"Expected bytes: {expected_bytes}",
                        f"Actual bytes:   {actual_bytes}",
                    ]
                )
            )

    if mismatches:
        print("\nPinned snapshot bytes changed.")
        print("Restore snapshots to HEAD or re-run the snapshot refresh workflow intentionally.")
        print("\n" + "\n\n".join(mismatches))
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
