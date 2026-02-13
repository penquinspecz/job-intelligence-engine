"""
SignalCraft
Copyright (c) 2026 Chris Menendez.
All Rights Reserved.
See LICENSE for permitted use.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ji_engine.proof.bundle import sha256_file


@dataclass(frozen=True)
class OnPremProofConfig:
    run_id: str
    namespace: str
    overlay_path: str
    k8s_context: str
    mode: str


def build_onprem_checklist(config: OnPremProofConfig) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "run_id": config.run_id,
        "mode": config.mode,
        "namespace": config.namespace,
        "k8s_context": config.k8s_context,
        "overlay_path": config.overlay_path,
        "preflight": [
            "kubectl context resolves and points to intended k3s cluster",
            "storage class local-path is present",
            "jobintel namespace exists or can be created from overlay",
            "required secrets exist out-of-band (no plaintext secrets in repo)",
        ],
        "execution_commands": [
            f"kubectl --context {config.k8s_context} apply -k {config.overlay_path}",
            f"kubectl --context {config.k8s_context} -n {config.namespace} get cronjob,deploy,svc,pvc,ingress -o wide",
            (
                f"kubectl --context {config.k8s_context} -n {config.namespace} "
                f"create job --from=cronjob/jobintel-daily jobintel-proof-{config.run_id}"
            ),
            f"kubectl --context {config.k8s_context} -n {config.namespace} logs job/jobintel-proof-{config.run_id}",
        ],
        "success_criteria": [
            "all nodes Ready with no flapping during proof window",
            "control-plane pods stable (no repeated restarts/crash loops)",
            "CronJob present and repeated job runs succeed in the window",
            "time sync (NTP) verified on all nodes via host evidence",
            "storage mount evidence confirms USB-backed persistent paths",
            "PVCs Bound and state survives pod restart",
            "Ingress exists and TLS secret referenced",
            "VPN-first access is documented; no open WAN exposure by default",
        ],
        "expected_receipts": [
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
        ],
        "failure_triage": [
            "if nodes NotReady: check k3s service status and disk pressure first",
            "if PVC Pending: inspect storageclass and local-path provisioner",
            "if CronJob run fails: inspect pod describe and job logs",
            "if ingress unreachable: verify Traefik service, DNS, and TLS secret",
        ],
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_manifest(bundle_dir: Path, *, run_id: str) -> Path:
    files = sorted(p for p in bundle_dir.glob("*") if p.is_file() and p.name != "manifest.json")
    payload = {
        "schema_version": 1,
        "run_id": run_id,
        "files": [
            {
                "path": path.name,
                "sha256": sha256_file(path),
                "size_bytes": path.stat().st_size,
            }
            for path in files
        ],
    }
    manifest_path = bundle_dir / "manifest.json"
    write_json(manifest_path, payload)
    return manifest_path
