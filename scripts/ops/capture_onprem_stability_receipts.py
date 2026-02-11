#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from ji_engine.proof.bundle import redact_text, sha256_file  # noqa: E402
from ji_engine.proof.onprem_stability import (  # noqa: E402
    CHECKPOINT_DIR,
    OnPremStabilityConfig,
    build_onprem_stability_plan,
    checkpoint_dir_name,
    expected_checkpoint_count,
)
from ji_engine.utils.time import utc_now_z  # noqa: E402


@dataclass(frozen=True)
class CheckpointSummary:
    index: int
    captured_at: str
    node_ready_count: int
    node_total_count: int
    notready_nodes: list[str]
    node_warning_events: int
    kube_system_restart_total: int
    kube_system_crashloop_count: int
    namespace_restart_total: int
    namespace_crashloop_count: int


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, check=False, capture_output=True, text=True)


def _utc_iso() -> str:
    return utc_now_z(seconds_precision=True)


def _resolve_context(explicit: str) -> str:
    if explicit:
        return explicit
    result = _run(["kubectl", "config", "current-context"])
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout).strip() or "unable to resolve kubectl context")
    return result.stdout.strip()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_if_missing(path: Path, text: str) -> None:
    if path.exists():
        return
    _write_text(path, text)


_EVIDENCE_TEMPLATE_COMMANDS = {
    "timedatectl status",
    "chronyc tracking || true",
    "chronyc sources -v || true",
    "systemctl status k3s || systemctl status k3s-agent || true",
    "journalctl -u k3s -n 80 --no-pager || true",
    "journalctl -u k3s-agent -n 80 --no-pager || true",
    "lsblk -o NAME,MODEL,SIZE,TYPE,MOUNTPOINT,FSTYPE",
    "findmnt -o TARGET,SOURCE,FSTYPE,OPTIONS | grep -E '/var/lib/rancher|/app|/srv|/mnt' || true",
    "mount | grep -E 'mmcblk|sd[a-z]|nvme' || true",
    "getent hosts jobintel.internal || true",
    "dig +short jobintel.internal || true",
    "curl -vk https://jobintel.internal/healthz || true",
    "openssl s_client -connect jobintel.internal:443 -servername jobintel.internal < /dev/null || true",
}


def _write_templates(bundle_dir: Path) -> list[str]:
    files: list[str] = []
    host_timesync = bundle_dir / "host_timesync_evidence.txt"
    _write_if_missing(
        host_timesync,
        "\n".join(
            [
                "# Capture on each node and paste output below (or attach separate host logs).",
                "timedatectl status",
                "chronyc tracking || true",
                "chronyc sources -v || true",
                "",
            ]
        ),
    )
    files.append(host_timesync.name)

    host_k3s = bundle_dir / "host_k3s_service_evidence.txt"
    _write_if_missing(
        host_k3s,
        "\n".join(
            [
                "# Capture on each node and paste output below (or attach separate host logs).",
                "systemctl status k3s || systemctl status k3s-agent || true",
                "journalctl -u k3s -n 80 --no-pager || true",
                "journalctl -u k3s-agent -n 80 --no-pager || true",
                "",
            ]
        ),
    )
    files.append(host_k3s.name)

    host_storage = bundle_dir / "host_storage_evidence.txt"
    _write_if_missing(
        host_storage,
        "\n".join(
            [
                "# Capture on each node and paste output below (or attach separate host logs).",
                "lsblk -o NAME,MODEL,SIZE,TYPE,MOUNTPOINT,FSTYPE",
                "findmnt -o TARGET,SOURCE,FSTYPE,OPTIONS | grep -E '/var/lib/rancher|/app|/srv|/mnt' || true",
                "mount | grep -E 'mmcblk|sd[a-z]|nvme' || true",
                "",
            ]
        ),
    )
    files.append(host_storage.name)

    ingress = bundle_dir / "ingress_dns_tls_evidence.txt"
    _write_if_missing(
        ingress,
        "\n".join(
            [
                "# Capture from a VPN-connected host or within the LAN.",
                "getent hosts jobintel.internal || true",
                "dig +short jobintel.internal || true",
                "curl -vk https://jobintel.internal/healthz || true",
                "openssl s_client -connect jobintel.internal:443 -servername jobintel.internal < /dev/null || true",
                "",
            ]
        ),
    )
    files.append(ingress.name)

    observations = bundle_dir / "proof_observations.md"
    _write_if_missing(
        observations,
        "\n".join(
            [
                "# 72h Stability Observations",
                "",
                "Use this file to note any anomalies or operational actions during the window.",
                "",
                "## Checkpoints",
                "",
                "### T+00h",
                "- timestamp_utc:",
                "- node_ready_count:",
                "- notready_nodes:",
                "- kube_system_restart_delta:",
                "- namespace_restart_delta:",
                "- crashloop_count:",
                "- notes:",
                "",
                "### T+24h",
                "- timestamp_utc:",
                "- node_ready_count:",
                "- notready_nodes:",
                "- kube_system_restart_delta:",
                "- namespace_restart_delta:",
                "- crashloop_count:",
                "- notes:",
                "",
                "### T+48h",
                "- timestamp_utc:",
                "- node_ready_count:",
                "- notready_nodes:",
                "- kube_system_restart_delta:",
                "- namespace_restart_delta:",
                "- crashloop_count:",
                "- notes:",
                "",
                "### T+72h",
                "- timestamp_utc:",
                "- node_ready_count:",
                "- notready_nodes:",
                "- kube_system_restart_delta:",
                "- namespace_restart_delta:",
                "- crashloop_count:",
                "- notes:",
                "",
            ]
        ),
    )
    files.append(observations.name)
    return files


def _write_capture_script(bundle_dir: Path, *, namespace: str, context: str) -> str:
    capture = bundle_dir / "capture_commands.sh"
    _write_text(
        capture,
        "\n".join(
            [
                "#!/usr/bin/env bash",
                "set -euo pipefail",
                "",
                f'CTX="{context}"',
                f'NS="{namespace}"',
                "",
                'kubectl --context "$CTX" get nodes -o json > nodes.json',
                'kubectl --context "$CTX" get events --all-namespaces '
                "--field-selector=involvedObject.kind=Node,type=Warning -o json > node_notready_events.json",
                'kubectl --context "$CTX" -n kube-system get pods -o json > kube_system_pods.json',
                'kubectl --context "$CTX" -n "$NS" get pods -o json > namespace_pods.json',
                'kubectl --context "$CTX" -n "$NS" get events -o json > namespace_events.json',
                'kubectl --context "$CTX" get nodes -o wide > nodes_summary.log',
                'kubectl --context "$CTX" -n kube-system get pods '
                "-o custom-columns=NAME:.metadata.name,PHASE:.status.phase,RESTARTS:.status.containerStatuses[*].restartCount "
                "> kube_system_restarts.log",
                'kubectl --context "$CTX" -n "$NS" get pods '
                "-o custom-columns=NAME:.metadata.name,PHASE:.status.phase,RESTARTS:.status.containerStatuses[*].restartCount "
                "> namespace_restarts.log",
                'kubectl --context "$CTX" -n "$NS" get events --sort-by=.metadata.creationTimestamp '
                "> namespace_events.log",
                "",
            ]
        ),
    )
    capture.chmod(0o755)
    return capture.name


def _write_bundle_readme(bundle_dir: Path) -> str:
    readme = bundle_dir / "README.md"
    _write_text(
        readme,
        "\n".join(
            [
                "# On-Prem 72h Stability Proof Bundle",
                "",
                "This bundle captures receipts for the Milestone 4 on-prem 72h stability proof.",
                "",
                "## Plan mode",
                "```bash",
                "python scripts/ops/capture_onprem_stability_receipts.py --plan \\",
                "  --run-id 20260207T120000Z \\",
                "  --output-dir ops/proof/bundles \\",
                "  --namespace jobintel \\",
                "  --cluster-context <k3s-context>",
                "```",
                "",
                "## Capture one checkpoint (trial)",
                "```bash",
                "python scripts/ops/capture_onprem_stability_receipts.py --execute \\",
                "  --run-id 20260207T120000Z \\",
                "  --output-dir ops/proof/bundles \\",
                "  --namespace jobintel \\",
                "  --cluster-context <k3s-context> \\",
                "  --checkpoint-index 0",
                "```",
                "",
                "## 72h loop (recommended)",
                "```bash",
                "python scripts/ops/capture_onprem_stability_receipts.py --execute --loop \\",
                "  --run-id 20260207T120000Z \\",
                "  --output-dir ops/proof/bundles \\",
                "  --namespace jobintel \\",
                "  --cluster-context <k3s-context> \\",
                "  --window-hours 72 \\",
                "  --interval-minutes 360",
                "```",
                "",
                "If SSH is available, pass --ssh-host for each node to auto-capture",
                "k3s service status, NTP, and storage evidence. Otherwise fill the",
                "host evidence templates manually and re-run with --finalize.",
                "",
                "Finalize (requires templates filled; pass --allow-missing-host-evidence to override):",
                "```bash",
                "python scripts/ops/capture_onprem_stability_receipts.py --finalize \\",
                "  --run-id 20260207T120000Z \\",
                "  --output-dir ops/proof/bundles \\",
                "  --namespace jobintel \\",
                "  --cluster-context <k3s-context>",
                "```",
                "",
            ]
        ),
    )
    return readme.name


def _write_manifest(bundle_dir: Path, *, run_id: str) -> Path:
    files = sorted(
        [path for path in bundle_dir.rglob("*") if path.is_file() and path.name != "manifest.json"],
        key=lambda p: p.as_posix(),
    )
    payload = {
        "schema_version": 1,
        "run_id": run_id,
        "files": [
            {
                "path": path.relative_to(bundle_dir).as_posix(),
                "sha256": sha256_file(path),
                "size_bytes": path.stat().st_size,
            }
            for path in files
        ],
    }
    manifest_path = bundle_dir / "manifest.json"
    _write_json(manifest_path, payload)
    return manifest_path


def _ensure_checkpoint_dir(bundle_dir: Path, index: int) -> Path:
    checkpoint_dir = bundle_dir / CHECKPOINT_DIR / checkpoint_dir_name(index)
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    return checkpoint_dir


def _run_json(cmd: list[str]) -> dict[str, Any]:
    result = _run(cmd)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(f"command failed: {' '.join(cmd)} :: {detail}")
    return json.loads(result.stdout)


def _pod_restart_total(pods: dict[str, Any]) -> int:
    total = 0
    for pod in pods.get("items", []):
        statuses = pod.get("status", {}).get("containerStatuses", []) or []
        for status in statuses:
            total += int(status.get("restartCount", 0) or 0)
    return total


def _pod_crashloop_count(pods: dict[str, Any]) -> int:
    count = 0
    for pod in pods.get("items", []):
        statuses = pod.get("status", {}).get("containerStatuses", []) or []
        for status in statuses:
            waiting = status.get("state", {}).get("waiting", {})
            if waiting.get("reason") == "CrashLoopBackOff":
                count += 1
                break
    return count


def _summarize_nodes(nodes: dict[str, Any]) -> tuple[int, list[str]]:
    not_ready: list[str] = []
    for node in nodes.get("items", []):
        conditions = node.get("status", {}).get("conditions", []) or []
        ready = next((c for c in conditions if c.get("type") == "Ready"), {})
        if ready.get("status") != "True":
            not_ready.append(node.get("metadata", {}).get("name", "unknown"))
    return len(nodes.get("items", [])), not_ready


def _capture_checkpoint(
    *,
    checkpoint_dir: Path,
    context: str,
    namespace: str,
    index: int,
    captured_at: str,
) -> CheckpointSummary:
    nodes = _run_json(["kubectl", "--context", context, "get", "nodes", "-o", "json"])
    node_events = _run_json(
        [
            "kubectl",
            "--context",
            context,
            "get",
            "events",
            "--all-namespaces",
            "--field-selector=involvedObject.kind=Node,type=Warning",
            "-o",
            "json",
        ]
    )
    kube_system_pods = _run_json(["kubectl", "--context", context, "-n", "kube-system", "get", "pods", "-o", "json"])
    namespace_pods = _run_json(["kubectl", "--context", context, "-n", namespace, "get", "pods", "-o", "json"])
    namespace_events = _run_json(["kubectl", "--context", context, "-n", namespace, "get", "events", "-o", "json"])
    nodes_summary = _run(["kubectl", "--context", context, "get", "nodes", "-o", "wide"])
    kube_system_restarts = _run(
        [
            "kubectl",
            "--context",
            context,
            "-n",
            "kube-system",
            "get",
            "pods",
            "-o",
            "custom-columns=NAME:.metadata.name,PHASE:.status.phase,RESTARTS:.status.containerStatuses[*].restartCount",
        ]
    )
    namespace_restarts = _run(
        [
            "kubectl",
            "--context",
            context,
            "-n",
            namespace,
            "get",
            "pods",
            "-o",
            "custom-columns=NAME:.metadata.name,PHASE:.status.phase,RESTARTS:.status.containerStatuses[*].restartCount",
        ]
    )
    namespace_events_summary = _run(
        [
            "kubectl",
            "--context",
            context,
            "-n",
            namespace,
            "get",
            "events",
            "--sort-by=.metadata.creationTimestamp",
        ]
    )
    if nodes_summary.returncode != 0:
        raise RuntimeError((nodes_summary.stderr or nodes_summary.stdout).strip() or "nodes summary failed")
    if kube_system_restarts.returncode != 0:
        raise RuntimeError((kube_system_restarts.stderr or kube_system_restarts.stdout).strip() or "restarts failed")
    if namespace_restarts.returncode != 0:
        raise RuntimeError(
            (namespace_restarts.stderr or namespace_restarts.stdout).strip() or "namespace restarts failed"
        )
    if namespace_events_summary.returncode != 0:
        raise RuntimeError(
            (namespace_events_summary.stderr or namespace_events_summary.stdout).strip()
            or "namespace events summary failed"
        )

    _write_json(checkpoint_dir / "nodes.json", nodes)
    _write_json(checkpoint_dir / "node_notready_events.json", node_events)
    _write_json(checkpoint_dir / "kube_system_pods.json", kube_system_pods)
    _write_json(checkpoint_dir / "namespace_pods.json", namespace_pods)
    _write_json(checkpoint_dir / "namespace_events.json", namespace_events)
    _write_text(checkpoint_dir / "nodes_summary.log", redact_text(nodes_summary.stdout))
    _write_text(checkpoint_dir / "kube_system_restarts.log", redact_text(kube_system_restarts.stdout))
    _write_text(checkpoint_dir / "namespace_restarts.log", redact_text(namespace_restarts.stdout))
    _write_text(checkpoint_dir / "namespace_events.log", redact_text(namespace_events_summary.stdout))

    node_total, not_ready = _summarize_nodes(nodes)
    summary = CheckpointSummary(
        index=index,
        captured_at=captured_at,
        node_ready_count=node_total - len(not_ready),
        node_total_count=node_total,
        notready_nodes=not_ready,
        node_warning_events=len(node_events.get("items", [])),
        kube_system_restart_total=_pod_restart_total(kube_system_pods),
        kube_system_crashloop_count=_pod_crashloop_count(kube_system_pods),
        namespace_restart_total=_pod_restart_total(namespace_pods),
        namespace_crashloop_count=_pod_crashloop_count(namespace_pods),
    )
    _write_json(checkpoint_dir / "summary.json", summary.__dict__)
    return summary


def _parse_summary(path: Path) -> CheckpointSummary:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return CheckpointSummary(
        index=int(payload["index"]),
        captured_at=str(payload["captured_at"]),
        node_ready_count=int(payload["node_ready_count"]),
        node_total_count=int(payload["node_total_count"]),
        notready_nodes=list(payload["notready_nodes"]),
        node_warning_events=int(payload["node_warning_events"]),
        kube_system_restart_total=int(payload["kube_system_restart_total"]),
        kube_system_crashloop_count=int(payload["kube_system_crashloop_count"]),
        namespace_restart_total=int(payload["namespace_restart_total"]),
        namespace_crashloop_count=int(payload["namespace_crashloop_count"]),
    )


def _evidence_filled(path: Path) -> bool:
    if not path.exists():
        return False
    content = path.read_text(encoding="utf-8")
    lines = [line.strip() for line in content.splitlines()]
    return any(line and not line.startswith("#") and line not in _EVIDENCE_TEMPLATE_COMMANDS for line in lines)


def _capture_host_evidence(
    *,
    bundle_dir: Path,
    ssh_hosts: list[str],
    ssh_user: str,
) -> list[str]:
    if not ssh_hosts:
        return []
    host_dir = bundle_dir / "host_evidence"
    host_dir.mkdir(parents=True, exist_ok=True)
    files: list[str] = []
    for host in ssh_hosts:
        target = f"{ssh_user}@{host}" if ssh_user else host
        timesync_cmd = [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=accept-new",
            target,
            "timedatectl status; chronyc tracking || true; chronyc sources -v || true",
        ]
        k3s_cmd = [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=accept-new",
            target,
            "systemctl status k3s || systemctl status k3s-agent || true",
        ]
        storage_cmd = [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=accept-new",
            target,
            "lsblk -o NAME,MODEL,SIZE,TYPE,MOUNTPOINT,FSTYPE; "
            "findmnt -o TARGET,SOURCE,FSTYPE,OPTIONS | grep -E '/var/lib/rancher|/app|/srv|/mnt' || true; "
            "mount | grep -E 'mmcblk|sd[a-z]|nvme' || true",
        ]
        for name, cmd in (
            (f"{host}-timesync.log", timesync_cmd),
            (f"{host}-k3s-service.log", k3s_cmd),
            (f"{host}-storage.log", storage_cmd),
        ):
            result = _run(cmd)
            if result.returncode != 0:
                detail = (result.stderr or result.stdout).strip()
                raise RuntimeError(f"ssh failed: {' '.join(cmd)} :: {detail}")
            _write_text(host_dir / name, redact_text(result.stdout))
            files.append(str(Path("host_evidence") / name))
    return files


def _summarize_receipt(
    *,
    bundle_dir: Path,
    run_id: str,
    mode: str,
    namespace: str,
    context: str,
    window_hours: int,
    interval_minutes: int,
    started_at: str,
    finished_at: str,
    captured_at: str,
    expected_checkpoints: int,
    max_kube_system_restarts: int,
    max_namespace_restarts: int,
    allow_missing_host_evidence: bool,
) -> dict[str, Any]:
    summaries = sorted(
        [p for p in (bundle_dir / "checkpoints").rglob("summary.json") if p.is_file()],
        key=lambda p: p.as_posix(),
    )
    parsed = [_parse_summary(path) for path in summaries]
    checkpoint_count = len(parsed)

    not_ready_seen = [item for item in parsed if item.notready_nodes]
    crashloops = [item for item in parsed if item.kube_system_crashloop_count > 0 or item.namespace_crashloop_count > 0]
    kube_system_totals = [item.kube_system_restart_total for item in parsed]
    namespace_totals = [item.namespace_restart_total for item in parsed]
    kube_system_delta = max(kube_system_totals) - min(kube_system_totals) if kube_system_totals else 0
    namespace_delta = max(namespace_totals) - min(namespace_totals) if namespace_totals else 0

    host_timesync_ok = _evidence_filled(bundle_dir / "host_timesync_evidence.txt")
    host_k3s_ok = _evidence_filled(bundle_dir / "host_k3s_service_evidence.txt")
    host_storage_ok = _evidence_filled(bundle_dir / "host_storage_evidence.txt")
    ingress_dns_tls_ok = _evidence_filled(bundle_dir / "ingress_dns_tls_evidence.txt")

    fail_reasons: list[str] = []
    if checkpoint_count == 0 and mode != "plan":
        fail_reasons.append("no_checkpoints_captured")
    if not_ready_seen:
        fail_reasons.append("node_notready_detected")
    if crashloops:
        fail_reasons.append("crashloopbackoff_detected")
    if kube_system_delta > max_kube_system_restarts:
        fail_reasons.append("kube_system_restart_delta_exceeds_threshold")
    if namespace_delta > max_namespace_restarts:
        fail_reasons.append("namespace_restart_delta_exceeds_threshold")
    if not allow_missing_host_evidence:
        if not host_timesync_ok:
            fail_reasons.append("host_timesync_evidence_missing")
        if not host_k3s_ok:
            fail_reasons.append("host_k3s_service_evidence_missing")
        if not host_storage_ok:
            fail_reasons.append("host_storage_evidence_missing")
        if not ingress_dns_tls_ok:
            fail_reasons.append("ingress_dns_tls_evidence_missing")

    status = "planned" if mode == "plan" else ("pass" if not fail_reasons else "fail")
    evidence_files = sorted(
        [
            path.relative_to(bundle_dir).as_posix()
            for path in bundle_dir.rglob("*")
            if path.is_file() and path.name != "receipt.json"
        ]
    )
    return {
        "schema_version": 1,
        "run_id": run_id,
        "mode": mode,
        "status": status,
        "started_at": started_at,
        "finished_at": finished_at,
        "captured_at": captured_at,
        "namespace": namespace,
        "k8s_context": context,
        "window_hours": window_hours,
        "interval_minutes": interval_minutes,
        "expected_checkpoints": expected_checkpoints,
        "checkpoint_count": checkpoint_count,
        "kube_system_restart_delta": kube_system_delta,
        "namespace_restart_delta": namespace_delta,
        "max_kube_system_restarts": max_kube_system_restarts,
        "max_namespace_restarts": max_namespace_restarts,
        "allow_missing_host_evidence": allow_missing_host_evidence,
        "host_evidence": {
            "timesync": "present" if host_timesync_ok else "missing",
            "k3s_service": "present" if host_k3s_ok else "missing",
            "storage": "present" if host_storage_ok else "missing",
            "ingress_dns_tls": "present" if ingress_dns_tls_ok else "missing",
        },
        "fail_reasons": fail_reasons,
        "evidence_files": evidence_files,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Capture on-prem k3s 72h stability receipts (plan-first, deterministic filenames)."
    )
    parser.add_argument("--plan", action="store_true", default=False, help="Plan mode (default when --execute unset).")
    parser.add_argument("--execute", action="store_true", help="Capture receipts now.")
    parser.add_argument("--finalize", action="store_true", help="Recompute receipt/manifest from existing files.")
    parser.add_argument("--output-dir", default="ops/proof/bundles")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--namespace", default="jobintel")
    parser.add_argument("--cluster-context", default="", help="kubectl context (defaults to current-context).")
    parser.add_argument("--window-hours", type=int, default=72)
    parser.add_argument("--interval-minutes", type=int, default=360)
    parser.add_argument("--checkpoint-index", type=int, default=0)
    parser.add_argument("--loop", action="store_true", help="Loop for the full window.")
    parser.add_argument("--max-checkpoints", type=int, default=0)
    parser.add_argument("--max-kube-system-restarts", type=int, default=0)
    parser.add_argument("--max-namespace-restarts", type=int, default=0)
    parser.add_argument("--ssh-host", action="append", default=[], dest="ssh_hosts")
    parser.add_argument("--ssh-user", default="")
    parser.add_argument(
        "--allow-missing-host-evidence",
        action="store_true",
        help="Allow finalize/pass without host evidence templates filled.",
    )
    parser.add_argument("--captured-at", default="", help=argparse.SUPPRESS)
    parser.add_argument("--started-at", default="", help=argparse.SUPPRESS)
    parser.add_argument("--finished-at", default="", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    run_id = args.run_id or _utc_iso().replace("-", "").replace(":", "")
    mode = "execute" if args.execute else "plan"
    context = args.cluster_context or "<current-context>"
    started_at = args.started_at or _utc_iso()
    captured_at = args.captured_at or _utc_iso()

    bundle_dir = (REPO_ROOT / args.output_dir / f"m4-{run_id}" / "onprem-72h").resolve()
    bundle_dir.mkdir(parents=True, exist_ok=True)

    config = OnPremStabilityConfig(
        run_id=run_id,
        namespace=args.namespace,
        k8s_context=context,
        window_hours=args.window_hours,
        interval_minutes=args.interval_minutes,
        mode=mode,
    )
    plan = build_onprem_stability_plan(config)
    _write_json(bundle_dir / "plan.json", plan)
    _write_bundle_readme(bundle_dir)
    _write_capture_script(bundle_dir, namespace=args.namespace, context=context)
    _write_templates(bundle_dir)

    expected = expected_checkpoint_count(
        window_hours=args.window_hours,
        interval_minutes=args.interval_minutes,
    )

    if args.execute:
        resolved_context = _resolve_context(args.cluster_context)
        context = resolved_context
        if args.ssh_hosts:
            _capture_host_evidence(
                bundle_dir=bundle_dir,
                ssh_hosts=args.ssh_hosts,
                ssh_user=args.ssh_user,
            )

        if args.loop:
            checkpoints = expected
            if args.max_checkpoints:
                checkpoints = min(checkpoints, args.max_checkpoints)
            for index in range(checkpoints):
                checkpoint_dir = _ensure_checkpoint_dir(bundle_dir, index)
                _capture_checkpoint(
                    checkpoint_dir=checkpoint_dir,
                    context=context,
                    namespace=args.namespace,
                    index=index,
                    captured_at=_utc_iso(),
                )
                if index < checkpoints - 1:
                    time.sleep(args.interval_minutes * 60)
        else:
            checkpoint_dir = _ensure_checkpoint_dir(bundle_dir, args.checkpoint_index)
            _capture_checkpoint(
                checkpoint_dir=checkpoint_dir,
                context=context,
                namespace=args.namespace,
                index=args.checkpoint_index,
                captured_at=_utc_iso(),
            )

    if args.finalize or args.execute or mode == "plan":
        finished_at = args.finished_at or _utc_iso()
        receipt = _summarize_receipt(
            bundle_dir=bundle_dir,
            run_id=run_id,
            mode=mode if not args.finalize else "finalized",
            namespace=args.namespace,
            context=context,
            window_hours=args.window_hours,
            interval_minutes=args.interval_minutes,
            started_at=started_at,
            finished_at=finished_at,
            captured_at=captured_at,
            expected_checkpoints=expected,
            max_kube_system_restarts=args.max_kube_system_restarts,
            max_namespace_restarts=args.max_namespace_restarts,
            allow_missing_host_evidence=bool(args.allow_missing_host_evidence),
        )
        _write_json(bundle_dir / "receipt.json", receipt)
        _write_manifest(bundle_dir, run_id=run_id)

    print(f"onprem_stability_mode={mode}")
    print(f"onprem_stability_run_id={run_id}")
    print(f"onprem_stability_bundle={bundle_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
