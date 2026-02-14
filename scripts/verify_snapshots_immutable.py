#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

from ji_engine.providers.registry import load_providers_config
from ji_engine.utils.verification import compute_sha256_bytes


def _required_snapshot_manifest_paths(providers_config_path: Path) -> list[str]:
    providers = load_providers_config(providers_config_path)
    required: set[str] = set()
    for provider in providers:
        if not provider.get("enabled", True):
            continue
        if not provider.get("snapshot_enabled", True):
            continue
        mode = str(provider.get("mode") or "snapshot").strip().lower()
        if mode not in {"snapshot", "auto"}:
            continue
        required.add(str(provider["snapshot_path"]))
    return sorted(required)


def main() -> int:
    manifest_path = Path("tests/fixtures/golden/snapshot_bytes.manifest.json")
    providers_config_path = Path("config/providers.json")
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

    missing_manifest_entries: list[str] = []
    for required_path in _required_snapshot_manifest_paths(providers_config_path):
        if required_path not in manifest:
            missing_manifest_entries.append(required_path)
    if missing_manifest_entries:
        mismatches.append(
            "Manifest missing enabled snapshot provider fixture entries:\n"
            + "\n".join(f"- {path}" for path in missing_manifest_entries)
        )

    if mismatches:
        print("\nPinned snapshot bytes changed.")
        print("Restore snapshots to HEAD or re-run the snapshot refresh workflow intentionally.")
        print(
            "For an intentional single-provider baseline update, run:\n"
            "  PYTHONPATH=src .venv/bin/python scripts/provider_authoring.py "
            "update-snapshot-manifest --provider <provider_id>"
        )
        print("If config/providers.json changed, include `snapshot manifest update required: yes|no` in PR body.")
        print("\n" + "\n\n".join(mismatches))
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
