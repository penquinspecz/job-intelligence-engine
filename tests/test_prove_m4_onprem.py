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
        "--started-at",
        "2026-02-07T12:00:00Z",
        "--finished-at",
        "2026-02-07T12:00:01Z",
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
        "evidence_files": [
            "capture_commands.sh",
            "checklist.json",
            "host_storage_evidence.txt",
            "host_timesync_evidence.txt",
            "proof_observations.md",
        ],
        "evidence_paths": {
            "capture_commands.sh": str((proof_dir / "capture_commands.sh").resolve()),
            "checklist.json": str((proof_dir / "checklist.json").resolve()),
            "host_storage_evidence.txt": str((proof_dir / "host_storage_evidence.txt").resolve()),
            "host_timesync_evidence.txt": str((proof_dir / "host_timesync_evidence.txt").resolve()),
            "proof_observations.md": str((proof_dir / "proof_observations.md").resolve()),
        },
        "finished_at": "2026-02-07T12:00:01Z",
        "k8s_context": "k3s-main",
        "mode": "plan",
        "namespace": "jobintel",
        "overlay_path": "ops/k8s/jobintel/overlays/onprem",
        "requirement_evidence": {
            "control_plane_stability": ["kube_system_pods.log", "kube_system_restarts.log", "events.log"],
            "cronjob_success_over_time": ["cronjob_history.log", "cronjob_describe.log", "jobs.log", "restarts.log"],
            "network_ingress_tls": ["workloads.log", "events.log", "proof_observations.md"],
            "node_readiness_stability": ["nodes_wide.log", "node_conditions.json", "node_notready_events.log"],
            "storage_usb_vs_sd": ["host_storage_evidence.txt", "workloads.log"],
            "time_sync": ["host_timesync_evidence.txt"],
            "workload_health": ["pods_wide.log", "restarts.log"],
        },
        "run_id": "20260207T120000Z",
        "schema_version": 1,
        "started_at": "2026-02-07T12:00:00Z",
        "status": "planned",
    }

    manifest = json.loads((proof_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["schema_version"] == 1
    assert manifest["run_id"] == "20260207T120000Z"
    assert [item["path"] for item in manifest["files"]] == [
        "capture_commands.sh",
        "checklist.json",
        "host_storage_evidence.txt",
        "host_timesync_evidence.txt",
        "proof_observations.md",
        "receipt.json",
    ]
    for item in manifest["files"]:
        assert len(item["sha256"]) == 64
        assert item["size_bytes"] > 0


def test_receipt_schema_required_keys(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(prove_m4_onprem, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(prove_m4_onprem, "_run", lambda cmd: None)

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
        "--started-at",
        "2026-02-07T12:00:00Z",
        "--finished-at",
        "2026-02-07T12:00:01Z",
    ]

    assert prove_m4_onprem.main(args) == 0

    proof_dir = tmp_path / "ops" / "proof" / "bundles" / "m4-20260207T120000Z" / "onprem"
    receipt = json.loads((proof_dir / "receipt.json").read_text(encoding="utf-8"))
    required = {
        "schema_version",
        "run_id",
        "started_at",
        "finished_at",
        "captured_at",
        "mode",
        "namespace",
        "k8s_context",
        "requirement_evidence",
    }
    assert required.issubset(receipt.keys())
