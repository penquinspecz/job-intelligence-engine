from __future__ import annotations

import json
from pathlib import Path

from ji_engine.proof.bundle import write_bundle_manifest


def test_write_bundle_manifest_is_deterministic(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir(parents=True)
    f1 = bundle / "a.log"
    f2 = bundle / "proofs" / "x.json"
    f2.parent.mkdir(parents=True)
    f1.write_text("alpha\n", encoding="utf-8")
    f2.write_text('{"ok":true}\n', encoding="utf-8")

    manifest = write_bundle_manifest(
        bundle,
        run_id="2026-02-06T00:00:00Z",
        cluster_name="jobintel-eks",
        kube_context="ctx-a",
        bucket="bucket-a",
        prefix="jobintel",
        git_sha="deadbeef",
        files=[f2, f1],
    )
    payload = json.loads(manifest.read_text(encoding="utf-8"))

    assert payload["schema_version"] == 1
    assert payload["run_id"] == "2026-02-06T00:00:00Z"
    assert [entry["path"] for entry in payload["files"]] == ["a.log", "proofs/x.json"]
    assert all(len(entry["sha256"]) == 64 for entry in payload["files"])
