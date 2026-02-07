from __future__ import annotations

import json
from pathlib import Path

import scripts.ops.prove_m4_onprem as prove_m4_onprem


def test_plan_mode_is_deterministic_and_no_kubectl_calls(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(prove_m4_onprem, "REPO_ROOT", tmp_path)

    run_calls: list[list[str]] = []

    def fail_if_called(cmd):  # type: ignore[no-untyped-def]
        run_calls.append(list(cmd))
        raise AssertionError("_run should not be called in plan mode")

    monkeypatch.setattr(prove_m4_onprem, "_run", fail_if_called)

    args = [
        "--run-id",
        "20260207T120000Z",
        "--output-dir",
        "ops/proof/bundles",
        "--namespace",
        "jobintel",
        "--cluster-context",
        "k3s-main",
        "--overlay-path",
        "ops/k8s/jobintel/overlays/onprem",
        "--captured-at",
        "2026-02-07T12:05:00Z",
    ]

    assert prove_m4_onprem.main(args) == 0
    assert prove_m4_onprem.main(args) == 0
    assert run_calls == []

    proof_dir = tmp_path / "ops" / "proof" / "bundles" / "m4-20260207T120000Z" / "onprem"
    assert (proof_dir / "checklist.json").exists()
    assert (proof_dir / "receipt.json").exists()
    assert (proof_dir / "manifest.json").exists()

    receipt = json.loads((proof_dir / "receipt.json").read_text(encoding="utf-8"))
    assert receipt == {
        "captured_at": "2026-02-07T12:05:00Z",
        "evidence_files": ["checklist.json"],
        "k8s_context": "k3s-main",
        "mode": "plan",
        "namespace": "jobintel",
        "overlay_path": "ops/k8s/jobintel/overlays/onprem",
        "run_id": "20260207T120000Z",
        "schema_version": 1,
        "status": "planned",
    }

    manifest = json.loads((proof_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["schema_version"] == 1
    assert manifest["run_id"] == "20260207T120000Z"
    assert [item["path"] for item in manifest["files"]] == [
        "checklist.json",
        "receipt.json",
    ]
    for item in manifest["files"]:
        assert len(item["sha256"]) == 64
        assert item["size_bytes"] > 0
