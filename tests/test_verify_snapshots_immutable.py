from __future__ import annotations

import json
import os
from pathlib import Path

from scripts import verify_snapshots_immutable


def test_verify_snapshots_immutable_requires_manifest_entries_for_enabled_snapshot_providers(
    tmp_path: Path,
) -> None:
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    (tmp_path / "data" / "alpha_snapshots").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tests" / "fixtures" / "golden").mkdir(parents=True, exist_ok=True)
    (tmp_path / "data" / "alpha_snapshots" / "index.html").write_text("alpha", encoding="utf-8")

    providers_payload = {
        "schema_version": 1,
        "providers": [
            {
                "provider_id": "alpha",
                "display_name": "Alpha",
                "enabled": True,
                "careers_urls": ["https://alpha.example/jobs"],
                "allowed_domains": ["alpha.example"],
                "extraction_mode": "jsonld",
                "mode": "snapshot",
                "snapshot_enabled": True,
                "live_enabled": False,
                "snapshot_path": "data/alpha_snapshots/index.html",
            }
        ],
    }
    (tmp_path / "config" / "providers.json").write_text(
        json.dumps(providers_payload, sort_keys=True),
        encoding="utf-8",
    )
    # Empty manifest should fail because enabled snapshot provider is not pinned.
    (tmp_path / "tests" / "fixtures" / "golden" / "snapshot_bytes.manifest.json").write_text(
        "{}",
        encoding="utf-8",
    )

    original_cwd = Path.cwd()
    try:
        # Script resolves config/ + tests/fixtures paths from cwd.
        os.chdir(tmp_path)
        rc = verify_snapshots_immutable.main()
    finally:
        os.chdir(original_cwd)
    assert rc == 2
