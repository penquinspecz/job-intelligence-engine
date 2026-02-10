from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict


@dataclass(frozen=True)
class OnPremStabilityConfig:
    run_id: str
    namespace: str
    k8s_context: str
    window_hours: int
    interval_minutes: int
    mode: str


CHECKPOINT_DIR = "checkpoints"
CHECKPOINT_PREFIX = "checkpoint-"
REQUIRED_TEMPLATES = (
    "host_timesync_evidence.txt",
    "host_storage_evidence.txt",
    "host_k3s_service_evidence.txt",
    "ingress_dns_tls_evidence.txt",
)
REQUIRED_TOP_LEVEL_FILES = (
    "plan.json",
    "README.md",
    "receipt.json",
    "manifest.json",
    "capture_commands.sh",
    "proof_observations.md",
)
REQUIRED_RECEIPT_KEYS = (
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
    "kube_system_restart_delta",
    "namespace_restart_delta",
    "fail_reasons",
    "evidence_files",
)


def checkpoint_dir_name(index: int) -> str:
    return f"{CHECKPOINT_PREFIX}{index:03d}"


def expected_checkpoint_count(*, window_hours: int, interval_minutes: int) -> int:
    if interval_minutes <= 0:
        raise ValueError("interval_minutes must be > 0")
    total_minutes = window_hours * 60
    return int(math.ceil(total_minutes / interval_minutes)) + 1


def expected_checkpoint_files() -> list[str]:
    return [
        f"{CHECKPOINT_DIR}/{checkpoint_dir_name(0)}/nodes.json",
        f"{CHECKPOINT_DIR}/{checkpoint_dir_name(0)}/node_notready_events.json",
        f"{CHECKPOINT_DIR}/{checkpoint_dir_name(0)}/kube_system_pods.json",
        f"{CHECKPOINT_DIR}/{checkpoint_dir_name(0)}/namespace_pods.json",
        f"{CHECKPOINT_DIR}/{checkpoint_dir_name(0)}/namespace_events.json",
        f"{CHECKPOINT_DIR}/{checkpoint_dir_name(0)}/nodes_summary.log",
        f"{CHECKPOINT_DIR}/{checkpoint_dir_name(0)}/kube_system_restarts.log",
        f"{CHECKPOINT_DIR}/{checkpoint_dir_name(0)}/namespace_restarts.log",
        f"{CHECKPOINT_DIR}/{checkpoint_dir_name(0)}/namespace_events.log",
        f"{CHECKPOINT_DIR}/{checkpoint_dir_name(0)}/summary.json",
    ]


def validate_receipt_schema(payload: Dict[str, Any]) -> None:
    missing = [key for key in REQUIRED_RECEIPT_KEYS if key not in payload]
    if missing:
        raise ValueError(f"receipt missing keys: {', '.join(missing)}")
    if payload.get("schema_version") != 1:
        raise ValueError("receipt schema_version must be 1")
    if payload.get("status") not in {"planned", "pass", "fail", "finalized"}:
        raise ValueError("receipt status must be planned, pass, fail, or finalized")
    if not isinstance(payload.get("fail_reasons"), list):
        raise ValueError("receipt fail_reasons must be a list")
    if not isinstance(payload.get("evidence_files"), list):
        raise ValueError("receipt evidence_files must be a list")


def build_onprem_stability_plan(config: OnPremStabilityConfig) -> dict[str, Any]:
    checkpoints = expected_checkpoint_count(
        window_hours=config.window_hours,
        interval_minutes=config.interval_minutes,
    )
    expected_receipts = [
        *REQUIRED_TOP_LEVEL_FILES,
        *REQUIRED_TEMPLATES,
        *expected_checkpoint_files(),
    ]
    return {
        "schema_version": 1,
        "run_id": config.run_id,
        "mode": config.mode,
        "namespace": config.namespace,
        "k8s_context": config.k8s_context,
        "window_hours": config.window_hours,
        "interval_minutes": config.interval_minutes,
        "expected_checkpoints": checkpoints,
        "preflight": [
            "kubectl context resolves and points to intended k3s cluster",
            "nodes are Ready before starting stability window",
            "VPN access path is available (no WAN exposure)",
            "USB3 SSD mounted for persistent state; SD card is OS boot only",
        ],
        "collection_summary": [
            "node readiness and NotReady events (kubectl)",
            "kube-system pod restarts and crash loops (kubectl)",
            "jobintel namespace pod restarts and crash loops (kubectl)",
            "k3s service status per node (optional ssh or operator evidence)",
            "NTP/time sync status per node (optional ssh or operator evidence)",
            "storage mount evidence per node (optional ssh or operator evidence)",
        ],
        "success_criteria": [
            "all nodes Ready across the entire window",
            "no CrashLoopBackOff in kube-system or jobintel pods",
            "kube-system and jobintel restart deltas within thresholds",
            "k3s service status captured per node",
            "NTP/time sync evidence captured per node",
            "USB-backed storage evidence captured per node",
            "ingress DNS + TLS evidence captured",
        ],
        "failure_branches": [
            "if nodes NotReady: inspect k3s service logs and disk pressure",
            "if restarts spike: inspect pod describe and recent events",
            "if time sync drift: fix NTP/chrony before continuing window",
            "if ingress fails: verify VPN DNS, Traefik, and TLS secret",
        ],
        "required_templates": list(REQUIRED_TEMPLATES),
        "expected_receipts": expected_receipts,
    }
