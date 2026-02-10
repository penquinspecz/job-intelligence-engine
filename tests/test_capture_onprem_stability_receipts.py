from __future__ import annotations

import json
from pathlib import Path

import scripts.ops.capture_onprem_stability_receipts as capture
from ji_engine.proof.bundle import sha256_file
from ji_engine.proof.onprem_stability import validate_receipt_schema


def test_plan_mode_is_deterministic_and_no_kubectl_calls(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(capture, "REPO_ROOT", tmp_path)

    def fail_if_called(cmd):  # type: ignore[no-untyped-def]
        raise AssertionError("_run should not be called in plan mode")

    monkeypatch.setattr(capture, "_run", fail_if_called)

    args = [
        "--plan",
        "--run-id",
        "20260207T120000Z",
        "--output-dir",
        "ops/proof/bundles",
        "--namespace",
        "jobintel",
        "--cluster-context",
        "does-not-exist",
        "--window-hours",
        "72",
        "--interval-minutes",
        "360",
        "--captured-at",
        "2026-02-07T12:05:00Z",
        "--started-at",
        "2026-02-07T12:00:00Z",
        "--finished-at",
        "2026-02-07T12:00:01Z",
    ]

    assert capture.main(args) == 0
    assert capture.main(args) == 0

    bundle_dir = tmp_path / "ops" / "proof" / "bundles" / "m4-20260207T120000Z" / "onprem-72h"
    assert (bundle_dir / "plan.json").exists()
    assert (bundle_dir / "receipt.json").exists()
    assert (bundle_dir / "manifest.json").exists()
    assert (bundle_dir / "README.md").exists()
    assert (bundle_dir / "host_timesync_evidence.txt").exists()
    assert (bundle_dir / "host_k3s_service_evidence.txt").exists()
    assert (bundle_dir / "host_storage_evidence.txt").exists()
    assert (bundle_dir / "ingress_dns_tls_evidence.txt").exists()

    receipt = json.loads((bundle_dir / "receipt.json").read_text(encoding="utf-8"))
    assert receipt["schema_version"] == 1
    assert receipt["run_id"] == "20260207T120000Z"
    assert receipt["mode"] == "plan"
    assert receipt["status"] == "planned"

    manifest = json.loads((bundle_dir / "manifest.json").read_text(encoding="utf-8"))
    manifest_paths = [item["path"] for item in manifest["files"]]
    expected = sorted(
        [
            "README.md",
            "capture_commands.sh",
            "host_k3s_service_evidence.txt",
            "host_storage_evidence.txt",
            "host_timesync_evidence.txt",
            "ingress_dns_tls_evidence.txt",
            "plan.json",
            "proof_observations.md",
            "receipt.json",
        ]
    )
    assert manifest_paths == expected


def test_receipt_schema_required_keys(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(capture, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(capture, "_run", lambda cmd: None)

    args = [
        "--plan",
        "--run-id",
        "20260207T120000Z",
        "--output-dir",
        "ops/proof/bundles",
        "--namespace",
        "jobintel",
        "--cluster-context",
        "any-context-is-ok",
        "--window-hours",
        "72",
        "--interval-minutes",
        "360",
        "--captured-at",
        "2026-02-07T12:05:00Z",
        "--started-at",
        "2026-02-07T12:00:00Z",
        "--finished-at",
        "2026-02-07T12:00:01Z",
    ]

    assert capture.main(args) == 0
    bundle_dir = tmp_path / "ops" / "proof" / "bundles" / "m4-20260207T120000Z" / "onprem-72h"
    receipt = json.loads((bundle_dir / "receipt.json").read_text(encoding="utf-8"))
    required = {
        "schema_version",
        "run_id",
        "mode",
        "status",
        "started_at",
        "finished_at",
        "captured_at",
        "namespace",
        "k8s_context",
        "window_hours",
        "interval_minutes",
        "expected_checkpoints",
        "checkpoint_count",
        "fail_reasons",
        "evidence_files",
    }
    assert required.issubset(receipt.keys())


def test_receipt_schema_validation_accepts_pass_payload() -> None:
    payload = {
        "schema_version": 1,
        "run_id": "20260207T120000Z",
        "mode": "finalized",
        "status": "pass",
        "started_at": "2026-02-07T12:00:00Z",
        "finished_at": "2026-02-10T12:00:00Z",
        "captured_at": "2026-02-10T12:00:01Z",
        "namespace": "jobintel",
        "k8s_context": "k3s-main",
        "window_hours": 72,
        "interval_minutes": 360,
        "expected_checkpoints": 13,
        "checkpoint_count": 13,
        "kube_system_restart_delta": 0,
        "namespace_restart_delta": 0,
        "fail_reasons": [],
        "evidence_files": ["plan.json"],
    }
    validate_receipt_schema(payload)


def test_manifest_hashing_is_stable(tmp_path: Path) -> None:
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    file_a = bundle_dir / "a.txt"
    file_b = bundle_dir / "b.txt"
    file_a.write_text("alpha\n", encoding="utf-8")
    file_b.write_text("beta\n", encoding="utf-8")

    manifest_path = capture._write_manifest(bundle_dir, run_id="run-123")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    items = {item["path"]: item for item in manifest["files"]}

    assert items["a.txt"]["sha256"] == sha256_file(file_a)
    assert items["b.txt"]["sha256"] == sha256_file(file_b)
