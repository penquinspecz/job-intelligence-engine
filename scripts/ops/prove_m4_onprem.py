#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from ji_engine.proof.bundle import redact_text  # noqa: E402
from ji_engine.proof.onprem import (  # noqa: E402
    OnPremProofConfig,
    build_onprem_checklist,
    write_json,
    write_manifest,
)
from ji_engine.utils.time import utc_now, utc_now_z  # noqa: E402


def _utc_iso() -> str:
    return utc_now_z(seconds_precision=True)


def _default_run_id() -> str:
    return utc_now().strftime("%Y%m%dT%H%M%SZ")


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, check=False, capture_output=True, text=True)


def _resolve_context(explicit: str) -> str:
    if explicit:
        return explicit
    result = _run(["kubectl", "config", "current-context"])
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout).strip() or "unable to resolve kubectl context")
    return result.stdout.strip()


def _capture_kubectl_outputs(*, context: str, namespace: str, out_dir: Path) -> list[str]:
    commands = {
        "nodes_wide.log": ["kubectl", "--context", context, "get", "nodes", "-o", "wide"],
        "node_conditions.json": ["kubectl", "--context", context, "get", "nodes", "-o", "json"],
        "node_notready_events.log": [
            "kubectl",
            "--context",
            context,
            "get",
            "events",
            "--all-namespaces",
            "--sort-by=.metadata.creationTimestamp",
            "--field-selector=involvedObject.kind=Node,type=Warning",
        ],
        "kube_system_pods.log": [
            "kubectl",
            "--context",
            context,
            "-n",
            "kube-system",
            "get",
            "pods",
            "-o",
            "custom-columns=NAME:.metadata.name,PHASE:.status.phase,RESTARTS:.status.containerStatuses[*].restartCount,NODE:.spec.nodeName",
        ],
        "kube_system_restarts.log": [
            "kubectl",
            "--context",
            context,
            "-n",
            "kube-system",
            "get",
            "pods",
            "-o",
            "custom-columns=NAME:.metadata.name,RESTARTS:.status.containerStatuses[*].restartCount,START:.status.startTime",
        ],
        "node_leases.log": ["kubectl", "--context", context, "-n", "kube-node-lease", "get", "lease", "-o", "wide"],
        "pods_wide.log": [
            "kubectl",
            "--context",
            context,
            "-n",
            namespace,
            "get",
            "pods",
            "-o",
            "wide",
        ],
        "jobs.log": [
            "kubectl",
            "--context",
            context,
            "-n",
            namespace,
            "get",
            "jobs",
            "--sort-by=.metadata.creationTimestamp",
        ],
        "workloads.log": [
            "kubectl",
            "--context",
            context,
            "-n",
            namespace,
            "get",
            "cronjob,jobs,pods,pvc,svc,ingress",
            "-o",
            "wide",
        ],
        "events.log": [
            "kubectl",
            "--context",
            context,
            "-n",
            namespace,
            "get",
            "events",
            "--sort-by=.metadata.creationTimestamp",
        ],
        "restarts.log": [
            "kubectl",
            "--context",
            context,
            "-n",
            namespace,
            "get",
            "pods",
            "-o",
            "custom-columns=NAME:.metadata.name,PHASE:.status.phase,RESTARTS:.status.containerStatuses[*].restartCount",
        ],
        "cronjob_history.log": [
            "kubectl",
            "--context",
            context,
            "-n",
            namespace,
            "get",
            "jobs",
            "--sort-by=.metadata.creationTimestamp",
            "-o",
            "custom-columns=NAME:.metadata.name,OWNER:.metadata.ownerReferences[0].name,SUCCEEDED:.status.succeeded,FAILED:.status.failed,START:.status.startTime,COMPLETE:.status.completionTime",
        ],
        "cronjob_describe.log": [
            "kubectl",
            "--context",
            context,
            "-n",
            namespace,
            "describe",
            "cronjob",
            "jobintel-daily",
        ],
    }
    files: list[str] = []
    for filename, cmd in commands.items():
        result = _run(cmd)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            raise RuntimeError(f"command failed: {' '.join(cmd)} :: {detail}")
        target = out_dir / filename
        target.write_text(redact_text(result.stdout), encoding="utf-8")
        files.append(filename)
    return files


def _write_operator_evidence_templates(*, out_dir: Path) -> list[str]:
    files: list[str] = []
    timesync = out_dir / "host_timesync_evidence.txt"
    timesync.write_text(
        "\n".join(
            [
                "# Capture on each node and paste output below (or attach separate host logs).",
                "timedatectl status",
                "chronyc tracking || true",
                "chronyc sources -v || true",
                "",
            ]
        ),
        encoding="utf-8",
    )
    files.append(timesync.name)

    storage = out_dir / "host_storage_evidence.txt"
    storage.write_text(
        "\n".join(
            [
                "# Capture on each node and paste output below (or attach separate host logs).",
                "lsblk -o NAME,MODEL,SIZE,TYPE,MOUNTPOINT,FSTYPE",
                "findmnt -o TARGET,SOURCE,FSTYPE,OPTIONS | grep -E '/var/lib/rancher|/app|/srv|/mnt' || true",
                "mount | grep -E 'mmcblk|sd[a-z]|nvme' || true",
                "",
            ]
        ),
        encoding="utf-8",
    )
    files.append(storage.name)
    observations = out_dir / "proof_observations.md"
    observations.write_text(
        "\n".join(
            [
                "# 72h Boring Proof Observations",
                "",
                "Record periodic checkpoints at a fixed cadence (recommended: every 6-12 hours).",
                "Keep raw command outputs in sibling `*.log` files; summarize only key deltas here.",
                "",
                "## Checkpoints",
                "",
                "### T+00h",
                "- timestamp_utc:",
                "- node_ready_count:",
                "- notready_nodes:",
                "- control_plane_restarts_delta:",
                "- cronjob_recent_runs_ok:",
                "- pvc_bound_count:",
                "- ingress_tls_ok:",
                "- notes:",
                "",
                "### T+24h",
                "- timestamp_utc:",
                "- node_ready_count:",
                "- notready_nodes:",
                "- control_plane_restarts_delta:",
                "- cronjob_recent_runs_ok:",
                "- pvc_bound_count:",
                "- ingress_tls_ok:",
                "- notes:",
                "",
                "### T+48h",
                "- timestamp_utc:",
                "- node_ready_count:",
                "- notready_nodes:",
                "- control_plane_restarts_delta:",
                "- cronjob_recent_runs_ok:",
                "- pvc_bound_count:",
                "- ingress_tls_ok:",
                "- notes:",
                "",
                "### T+72h",
                "- timestamp_utc:",
                "- node_ready_count:",
                "- notready_nodes:",
                "- control_plane_restarts_delta:",
                "- cronjob_recent_runs_ok:",
                "- pvc_bound_count:",
                "- ingress_tls_ok:",
                "- notes:",
                "",
            ]
        ),
        encoding="utf-8",
    )
    files.append(observations.name)
    return files


def _write_capture_commands_template(*, out_dir: Path, namespace: str, context: str) -> list[str]:
    files: list[str] = []
    capture = out_dir / "capture_commands.sh"
    capture.write_text(
        "\n".join(
            [
                "#!/usr/bin/env bash",
                "set -euo pipefail",
                "",
                f'CTX="{context}"',
                f'NS="{namespace}"',
                "",
                'kubectl --context "$CTX" get nodes -o wide > nodes_wide.log',
                'kubectl --context "$CTX" get nodes -o json > node_conditions.json',
                'kubectl --context "$CTX" get events --all-namespaces --sort-by=.metadata.creationTimestamp '
                "--field-selector=involvedObject.kind=Node,type=Warning > node_notready_events.log",
                "",
                'kubectl --context "$CTX" -n kube-system get pods '
                "-o custom-columns=NAME:.metadata.name,PHASE:.status.phase,RESTARTS:.status.containerStatuses[*].restartCount,"
                "NODE:.spec.nodeName > kube_system_pods.log",
                'kubectl --context "$CTX" -n kube-system get pods '
                "-o custom-columns=NAME:.metadata.name,RESTARTS:.status.containerStatuses[*].restartCount,START:.status.startTime "
                "> kube_system_restarts.log",
                'kubectl --context "$CTX" -n kube-node-lease get lease -o wide > node_leases.log',
                "",
                'kubectl --context "$CTX" -n "$NS" get pods -o wide > pods_wide.log',
                'kubectl --context "$CTX" -n "$NS" get jobs --sort-by=.metadata.creationTimestamp > jobs.log',
                'kubectl --context "$CTX" -n "$NS" get cronjob,jobs,pods,pvc,svc,ingress -o wide > workloads.log',
                'kubectl --context "$CTX" -n "$NS" get events --sort-by=.metadata.creationTimestamp > events.log',
                'kubectl --context "$CTX" -n "$NS" get pods '
                "-o custom-columns=NAME:.metadata.name,PHASE:.status.phase,RESTARTS:.status.containerStatuses[*].restartCount "
                "> restarts.log",
                'kubectl --context "$CTX" -n "$NS" get jobs --sort-by=.metadata.creationTimestamp '
                "-o custom-columns=NAME:.metadata.name,OWNER:.metadata.ownerReferences[0].name,SUCCEEDED:.status.succeeded,"
                "FAILED:.status.failed,START:.status.startTime,COMPLETE:.status.completionTime > cronjob_history.log",
                'kubectl --context "$CTX" -n "$NS" describe cronjob jobintel-daily > cronjob_describe.log',
                "",
            ]
        ),
        encoding="utf-8",
    )
    capture.chmod(0o755)
    files.append(capture.name)
    return files


def _requirement_evidence_map() -> dict[str, list[str]]:
    return {
        "control_plane_stability": ["kube_system_pods.log", "kube_system_restarts.log", "events.log"],
        "node_readiness_stability": ["nodes_wide.log", "node_conditions.json", "node_notready_events.log"],
        "time_sync": ["host_timesync_evidence.txt"],
        "storage_usb_vs_sd": ["host_storage_evidence.txt", "workloads.log"],
        "cronjob_success_over_time": ["cronjob_history.log", "cronjob_describe.log", "jobs.log", "restarts.log"],
        "network_ingress_tls": ["workloads.log", "events.log", "proof_observations.md"],
        "workload_health": ["pods_wide.log", "restarts.log"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Plan-first on-prem Milestone 4 proof harness (72h boring proof checklist + optional kubectl captures)."
    )
    parser.add_argument("--run-id", default="", help="Proof run id. Defaults to UTC compact timestamp.")
    parser.add_argument("--output-dir", default="ops/proof/bundles", help="Base output directory.")
    parser.add_argument("--namespace", default="jobintel")
    parser.add_argument("--cluster-context", default="", help="kubectl context. Defaults to current-context.")
    parser.add_argument("--overlay-path", default="ops/k8s/jobintel/overlays/onprem")
    parser.add_argument("--execute", action="store_true", help="Capture kubectl receipts (read-only).")
    parser.add_argument("--plan", action="store_true", help="Explicit plan mode (default behavior).")
    parser.add_argument("--captured-at", default="", help=argparse.SUPPRESS)
    parser.add_argument("--started-at", default="", help=argparse.SUPPRESS)
    parser.add_argument("--finished-at", default="", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    run_id = args.run_id or _default_run_id()
    captured_at = args.captured_at or _utc_iso()
    started_at = args.started_at or _utc_iso()
    mode = "execute" if args.execute else "plan"
    context = args.cluster_context or "<current-context>"

    bundle_dir = (REPO_ROOT / args.output_dir / f"m4-{run_id}" / "onprem").resolve()
    bundle_dir.mkdir(parents=True, exist_ok=True)

    config = OnPremProofConfig(
        run_id=run_id,
        namespace=args.namespace,
        overlay_path=args.overlay_path,
        k8s_context=context,
        mode=mode,
    )
    checklist = build_onprem_checklist(config)
    write_json(bundle_dir / "checklist.json", checklist)

    evidence_files = ["checklist.json"]
    evidence_files.extend(
        _write_capture_commands_template(out_dir=bundle_dir, namespace=args.namespace, context=context)
    )
    evidence_files.extend(_write_operator_evidence_templates(out_dir=bundle_dir))
    resolved_context = context
    try:
        if args.execute:
            resolved_context = _resolve_context(args.cluster_context)
            captures = _capture_kubectl_outputs(context=resolved_context, namespace=args.namespace, out_dir=bundle_dir)
            evidence_files.extend(captures)
            status = "executed"
        else:
            status = "planned"
    except Exception as exc:
        print(f"prove_m4_onprem_status=failed error={exc!r}")
        return 2

    finished_at = args.finished_at or _utc_iso()
    evidence_paths = {name: str((bundle_dir / name).resolve()) for name in sorted(evidence_files)}
    receipt = {
        "schema_version": 1,
        "run_id": run_id,
        "started_at": started_at,
        "finished_at": finished_at,
        "captured_at": captured_at,
        "mode": mode,
        "namespace": args.namespace,
        "k8s_context": resolved_context,
        "overlay_path": args.overlay_path,
        "status": status,
        "evidence_files": sorted(evidence_files),
        "evidence_paths": evidence_paths,
        "requirement_evidence": _requirement_evidence_map(),
    }
    write_json(bundle_dir / "receipt.json", receipt)
    write_manifest(bundle_dir, run_id=run_id)

    print(f"prove_m4_onprem_mode={mode}")
    print(f"prove_m4_onprem_run_id={run_id}")
    print(f"prove_m4_onprem_bundle={bundle_dir}")
    print(f"prove_m4_onprem_receipt={bundle_dir / 'receipt.json'}")
    print(f"prove_m4_onprem_manifest={bundle_dir / 'manifest.json'}")
    print(f"prove_m4_onprem_status={status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
