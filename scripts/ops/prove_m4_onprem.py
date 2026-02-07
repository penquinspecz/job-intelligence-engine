#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime, timezone
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


def _utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _default_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


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
    args = parser.parse_args(argv)

    run_id = args.run_id or _default_run_id()
    captured_at = args.captured_at or _utc_iso()
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

    receipt = {
        "schema_version": 1,
        "run_id": run_id,
        "captured_at": captured_at,
        "mode": mode,
        "namespace": args.namespace,
        "k8s_context": resolved_context,
        "overlay_path": args.overlay_path,
        "status": status,
        "evidence_files": sorted(evidence_files),
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
