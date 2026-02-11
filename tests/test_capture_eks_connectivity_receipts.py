from __future__ import annotations

import json
from pathlib import Path

import scripts.ops.capture_eks_connectivity_receipts as capture


def test_plan_mode_is_deterministic_and_no_kubectl_calls(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(capture, "REPO_ROOT", tmp_path)

    def fail_if_called(cmd):  # type: ignore[no-untyped-def]
        raise AssertionError("_run should not be called in plan mode")

    monkeypatch.setattr(capture, "_run", fail_if_called)

    args = [
        "--plan",
        "--run-id",
        "m4-eks-proof-20260208T072500Z",
        "--output-dir",
        "ops/proof/bundles",
        "--cluster-context",
        "eks-jobintel-eks",
        "--namespace",
        "jobintel",
        "--captured-at",
        "2026-02-08T07:25:00Z",
        "--started-at",
        "2026-02-08T07:20:00Z",
        "--finished-at",
        "2026-02-08T07:20:01Z",
    ]

    assert capture.main(args) == 0
    assert capture.main(args) == 0

    bundle_dir = tmp_path / "ops" / "proof" / "bundles" / "m4-m4-eks-proof-20260208T072500Z" / "eks"
    assert (bundle_dir / "README.md").exists()
    assert (bundle_dir / "capture_commands.sh").exists()
    assert (bundle_dir / "receipt.json").exists()
    assert (bundle_dir / "manifest.json").exists()

    receipt = json.loads((bundle_dir / "receipt.json").read_text(encoding="utf-8"))
    assert receipt["schema_version"] == 1
    assert receipt["run_id"] == "m4-eks-proof-20260208T072500Z"
    assert receipt["mode"] == "plan"
    assert receipt["status"] == "planned"

    manifest = json.loads((bundle_dir / "manifest.json").read_text(encoding="utf-8"))
    paths = [item["path"] for item in manifest["files"]]
    assert paths == sorted(
        [
            "README.md",
            "capture_commands.sh",
            "receipt.json",
        ]
    )


def test_manifest_ignores_stale_files_from_previous_invocation(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(capture, "REPO_ROOT", tmp_path)
    args = [
        "--plan",
        "--run-id",
        "stable-run",
        "--output-dir",
        "ops/proof/bundles",
        "--captured-at",
        "2026-02-08T07:25:00Z",
        "--started-at",
        "2026-02-08T07:20:00Z",
        "--finished-at",
        "2026-02-08T07:20:01Z",
    ]
    assert capture.main(args) == 0

    bundle_dir = tmp_path / "ops" / "proof" / "bundles" / "m4-stable-run" / "eks"
    (bundle_dir / "stale.log").write_text("old run output\n", encoding="utf-8")

    assert capture.main(args) == 0
    manifest = json.loads((bundle_dir / "manifest.json").read_text(encoding="utf-8"))
    paths = [item["path"] for item in manifest["files"]]
    assert "stale.log" not in paths
