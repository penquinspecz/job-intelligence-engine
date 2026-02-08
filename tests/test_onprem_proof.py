from __future__ import annotations

from ji_engine.proof.onprem import OnPremProofConfig, build_onprem_checklist


def test_onprem_checklist_schema_and_expected_receipts_are_stable() -> None:
    config = OnPremProofConfig(
        run_id="20260207T120000Z",
        namespace="jobintel",
        overlay_path="ops/k8s/jobintel/overlays/onprem",
        k8s_context="k3s-main",
        mode="plan",
    )
    checklist = build_onprem_checklist(config)
    assert checklist["schema_version"] == 1
    assert checklist["run_id"] == "20260207T120000Z"
    assert checklist["mode"] == "plan"
    assert checklist["k8s_context"] == "k3s-main"
    assert checklist["expected_receipts"] == [
        "checklist.json",
        "receipt.json",
        "nodes_wide.log",
        "node_conditions.json",
        "node_notready_events.log",
        "kube_system_pods.log",
        "kube_system_restarts.log",
        "node_leases.log",
        "workloads.log",
        "cronjob_history.log",
        "cronjob_describe.log",
        "events.log",
        "restarts.log",
        "proof_observations.md",
        "host_timesync_evidence.txt",
        "host_storage_evidence.txt",
        "manifest.json",
    ]
