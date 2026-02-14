#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
ONPREM_PI_OVERLAY = REPO_ROOT / "ops" / "k8s" / "overlays" / "onprem-pi"
APPLY_CMD = ["kubectl", "apply", "-k", "ops/k8s/overlays/onprem-pi"]
REQUIRED_RESOURCE_IDS = {
    "Namespace/jobintel",
    "CronJob/jobintel-daily",
    "Deployment/jobintel-dashboard",
    "Service/jobintel-dashboard",
    "Ingress/jobintel-dashboard",
    "PersistentVolumeClaim/jobintel-data-pvc",
    "PersistentVolumeClaim/jobintel-state-pvc",
    "NetworkPolicy/dashboard-ingress-baseline",
}


class RehearsalError(RuntimeError):
    """Raised when deployment rehearsal preflights fail."""


def _run(cmd: list[str], cwd: Path = REPO_ROOT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, check=False, capture_output=True, text=True)


def _render_onprem_pi_manifest() -> str:
    render_cmd = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "k8s_render.py"),
        "--overlay",
        "onprem-pi",
        "--stdout",
    ]
    result = _run(render_cmd)
    if result.returncode != 0:
        stderr = result.stderr.strip() or "render failed"
        raise RehearsalError(f"k8s_render failed: {stderr}")
    return result.stdout


def _resource_id(doc: dict[str, Any]) -> str | None:
    kind = doc.get("kind")
    metadata = doc.get("metadata") if isinstance(doc.get("metadata"), dict) else {}
    name = metadata.get("name")
    if isinstance(kind, str) and isinstance(name, str) and kind and name:
        return f"{kind}/{name}"
    return None


def _validate_yaml_docs(manifest: str) -> set[str]:
    resource_ids: set[str] = set()
    for index, doc in enumerate(yaml.safe_load_all(manifest), start=1):
        if doc is None:
            continue
        if not isinstance(doc, dict):
            raise RehearsalError(f"manifest doc {index} is not a mapping")
        if not isinstance(doc.get("apiVersion"), str) or not doc["apiVersion"]:
            raise RehearsalError(f"manifest doc {index} missing apiVersion")
        if not isinstance(doc.get("kind"), str) or not doc["kind"]:
            raise RehearsalError(f"manifest doc {index} missing kind")
        rid = _resource_id(doc)
        if rid is not None:
            resource_ids.add(rid)
    if not resource_ids:
        raise RehearsalError("rendered manifest was empty")
    return resource_ids


def _validate_required_resources(resource_ids: set[str]) -> None:
    missing = sorted(REQUIRED_RESOURCE_IDS - resource_ids)
    if missing:
        raise RehearsalError(f"missing required resources: {', '.join(missing)}")


def _run_doctor() -> None:
    result = _run(["make", "doctor"])
    if result.returncode != 0:
        stderr = result.stderr.strip()
        stdout = result.stdout.strip()
        detail = stderr or stdout or "make doctor failed"
        raise RehearsalError(f"doctor failed: {detail}")


def _should_execute_apply(args_execute: bool) -> bool:
    if args_execute:
        return True
    dry_run = os.getenv("DRY_RUN", "1").strip()
    return dry_run == "0"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Rehearse on-prem Pi deployment without public exposure")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Apply overlay after successful preflight checks (default is dry-run).",
    )
    args = parser.parse_args(argv)

    if not ONPREM_PI_OVERLAY.exists():
        raise RehearsalError(f"overlay path missing: {ONPREM_PI_OVERLAY}")

    try:
        print("[onprem-rehearsal] doctor: running")
        _run_doctor()
        print("[onprem-rehearsal] doctor: pass")

        print("[onprem-rehearsal] render: ops/k8s/overlays/onprem-pi")
        manifest = _render_onprem_pi_manifest()
        resource_ids = _validate_yaml_docs(manifest)
        _validate_required_resources(resource_ids)
        print(f"[onprem-rehearsal] resources: pass ({len(resource_ids)} objects)")

        print("[onprem-rehearsal] apply command:")
        print(" ".join(APPLY_CMD))

        if _should_execute_apply(args.execute):
            apply_result = _run(APPLY_CMD)
            if apply_result.returncode != 0:
                detail = apply_result.stderr.strip() or apply_result.stdout.strip() or "kubectl apply failed"
                raise RehearsalError(f"apply failed: {detail}")
            print("[onprem-rehearsal] apply: pass")
        else:
            print("[onprem-rehearsal] DRY_RUN=1 (no apply executed)")
        return 0
    except RehearsalError as exc:
        print(f"[onprem-rehearsal] ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
