#!/usr/bin/env python3
from __future__ import annotations

try:
    import _bootstrap  # type: ignore  # noqa: F401
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

import argparse
import json
import os
import re
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from ji_engine.config import STATE_DIR
from ji_engine.utils.verification import compute_sha256_bytes

try:
    from scripts.schema_validate import resolve_named_schema_path, validate_payload
except ModuleNotFoundError:
    from schema_validate import resolve_named_schema_path, validate_payload  # type: ignore

OVERLAY_NAME = "onprem-pi"
APPLY_CMD = ["kubectl", "apply", "-k", f"ops/k8s/overlays/{OVERLAY_NAME}"]
FAILURE_CODES = {
    "DOCTOR_FAILED",
    "OVERLAY_RENDER_FAILED",
    "OVERLAY_RESOURCES_MISSING",
    "RECEIPT_SCHEMA_INVALID",
    "RECEIPT_WRITE_FAILED",
    "APPLY_FAILED",
    "UNEXPECTED_FAILURE",
}
_REQUIRED_RESOURCE_IDS = {
    "Namespace/jobintel",
    "CronJob/jobintel-daily",
    "Deployment/jobintel-dashboard",
    "Service/jobintel-dashboard",
    "Ingress/jobintel-dashboard",
    "PersistentVolumeClaim/jobintel-data-pvc",
    "PersistentVolumeClaim/jobintel-state-pvc",
    "NetworkPolicy/dashboard-ingress-baseline",
}
_RUN_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
WARNING_BANNER = "THIS IS A LOCAL DEPLOYMENT REHEARSAL. NO APPLY IS EXECUTED UNLESS REQUESTED."


class RehearsalError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _run(cmd: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, check=False, text=True, capture_output=True)


def _utc_run_id_now() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _safe_run_id(raw: str | None) -> str:
    candidate = (raw or "").strip() or _utc_run_id_now()
    if not _RUN_ID_RE.fullmatch(candidate):
        raise RehearsalError("UNEXPECTED_FAILURE", f"invalid run_id '{candidate}'")
    return candidate


def _should_write_receipt(args_write_receipt: bool) -> bool:
    if args_write_receipt:
        return True
    return os.getenv("WRITE_RECEIPT", "0").strip() == "1"


def _should_execute_apply(args_execute: bool) -> bool:
    if args_execute:
        return True
    return os.getenv("DRY_RUN", "1").strip() == "0"


def _git_sha(repo_root: Path) -> str:
    result = _run(["git", "rev-parse", "HEAD"], cwd=repo_root)
    if result.returncode != 0:
        return "unknown"
    value = result.stdout.strip()
    return value if value else "unknown"


def _render_overlay(repo_root: Path, overlay: str) -> str:
    cmd = [
        os.environ.get("PYTHON", "python3"),
        "scripts/k8s_render.py",
        "--overlay",
        overlay,
        "--stdout",
    ]
    result = _run(cmd, cwd=repo_root)
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "render failed"
        raise RehearsalError("OVERLAY_RENDER_FAILED", detail)
    return result.stdout


def _resource_id(doc: dict[str, Any]) -> str | None:
    metadata = doc.get("metadata") if isinstance(doc.get("metadata"), dict) else {}
    kind = doc.get("kind")
    name = metadata.get("name")
    if isinstance(kind, str) and kind and isinstance(name, str) and name:
        return f"{kind}/{name}"
    return None


def _validate_manifest(manifest: str) -> tuple[int, set[str]]:
    resource_ids: set[str] = set()
    for idx, doc in enumerate(yaml.safe_load_all(manifest), start=1):
        if doc is None:
            continue
        if not isinstance(doc, dict):
            raise RehearsalError("OVERLAY_RENDER_FAILED", f"manifest doc {idx} is not an object")
        if not isinstance(doc.get("apiVersion"), str):
            raise RehearsalError("OVERLAY_RENDER_FAILED", f"manifest doc {idx} missing apiVersion")
        if not isinstance(doc.get("kind"), str):
            raise RehearsalError("OVERLAY_RENDER_FAILED", f"manifest doc {idx} missing kind")
        rid = _resource_id(doc)
        if rid:
            resource_ids.add(rid)
    missing = sorted(_REQUIRED_RESOURCE_IDS - resource_ids)
    if missing:
        raise RehearsalError("OVERLAY_RESOURCES_MISSING", f"missing required resources: {', '.join(missing)}")
    return len(resource_ids), resource_ids


def _sample_hashes(manifest: str, limit: int) -> tuple[list[str], str, str]:
    sampled_lines = manifest.splitlines()[: max(limit, 0)]
    line_hashes = [compute_sha256_bytes(line.encode("utf-8")) for line in sampled_lines]
    sampled_blob = "\n".join(sampled_lines).encode("utf-8")
    sampled_sha = compute_sha256_bytes(sampled_blob)
    full_sha = compute_sha256_bytes(manifest.encode("utf-8"))
    return line_hashes, sampled_sha, full_sha


def _receipt_path(run_id: str) -> Path:
    return STATE_DIR / "rehearsals" / run_id / "onprem_rehearsal_receipt.v1.json"


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    fd, tmp_path = tempfile.mkstemp(prefix=f"{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(rendered)
        os.replace(tmp_path, path)
    finally:
        try:
            os.unlink(tmp_path)
        except FileNotFoundError:
            pass


def _build_receipt(
    *,
    run_id: str,
    git_sha: str,
    overlay: str,
    status: str,
    failure_code: str | None,
    rendered_resource_count: int,
    sampled_line_sha256: list[str],
    sampled_output_sha256: str,
    rendered_manifest_sha256: str,
    write_receipt: bool,
    apply_executed: bool,
) -> dict[str, Any]:
    return {
        "onprem_rehearsal_receipt_schema_version": 1,
        "run_id": run_id,
        "git_sha": git_sha,
        "overlay": overlay,
        "status": status,
        "failure_code": failure_code,
        "rendered_resource_count": rendered_resource_count,
        "sampled_line_count": len(sampled_line_sha256),
        "sampled_line_sha256": sampled_line_sha256,
        "sampled_output_sha256": sampled_output_sha256,
        "rendered_manifest_sha256": rendered_manifest_sha256,
        "write_receipt": write_receipt,
        "apply_executed": apply_executed,
        "commands": {
            "doctor": "make doctor",
            "render": f"python scripts/k8s_render.py --overlay {overlay} --stdout",
            "apply": " ".join(["kubectl", "apply", "-k", f"ops/k8s/overlays/{overlay}"]),
        },
    }


def _validate_receipt_schema(payload: dict[str, Any]) -> None:
    schema_path = resolve_named_schema_path("onprem_rehearsal_receipt", 1)
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    errors = validate_payload(payload, schema)
    if errors:
        raise RehearsalError("RECEIPT_SCHEMA_INVALID", "; ".join(errors))


def _write_receipt(payload: dict[str, Any], *, run_id: str) -> Path:
    _validate_receipt_schema(payload)
    target = _receipt_path(run_id)
    _atomic_write_json(target, payload)
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="On-prem Pi deployment rehearsal (dry-run by default)")
    parser.add_argument("--overlay", default=OVERLAY_NAME, choices=[OVERLAY_NAME])
    parser.add_argument("--run-id", default=None, help="Optional stable run_id override")
    parser.add_argument("--sample-lines", type=int, default=40)
    parser.add_argument("--write-receipt", action="store_true")
    parser.add_argument("--execute", action="store_true", help="Run kubectl apply after checks pass")
    args = parser.parse_args(argv)

    repo_root = Path(__file__).resolve().parents[1]
    run_id = _safe_run_id(args.run_id)
    write_receipt = _should_write_receipt(bool(args.write_receipt))
    apply_executed = False
    git_sha = _git_sha(repo_root)
    rendered_resource_count = 0
    line_hashes: list[str] = []
    sampled_sha = compute_sha256_bytes(b"")
    manifest_sha = compute_sha256_bytes(b"")
    status = "failed"
    failure_code: str | None = None

    print(WARNING_BANNER)

    try:
        doctor = _run(["make", "doctor"], cwd=repo_root)
        if doctor.returncode != 0:
            detail = doctor.stderr.strip() or doctor.stdout.strip() or "make doctor failed"
            raise RehearsalError("DOCTOR_FAILED", detail)

        manifest = _render_overlay(repo_root, args.overlay)
        rendered_resource_count, _resource_ids = _validate_manifest(manifest)
        line_hashes, sampled_sha, manifest_sha = _sample_hashes(manifest, args.sample_lines)

        apply_cmd = ["kubectl", "apply", "-k", f"ops/k8s/overlays/{args.overlay}"]
        print("apply command:")
        print(" ".join(apply_cmd))

        if _should_execute_apply(bool(args.execute)):
            result = _run(apply_cmd, cwd=repo_root)
            if result.returncode != 0:
                detail = result.stderr.strip() or result.stdout.strip() or "kubectl apply failed"
                raise RehearsalError("APPLY_FAILED", detail)
            apply_executed = True
            print("apply: pass")
        else:
            print("DRY_RUN=1 (no apply executed)")

        status = "success"
    except RehearsalError as exc:
        failure_code = exc.code if exc.code in FAILURE_CODES else "UNEXPECTED_FAILURE"
        print(f"[onprem-rehearsal] ERROR({failure_code}): {exc}")
    except Exception as exc:  # pragma: no cover - defensive fallback
        failure_code = "UNEXPECTED_FAILURE"
        print(f"[onprem-rehearsal] ERROR({failure_code}): {exc}")

    if write_receipt:
        receipt = _build_receipt(
            run_id=run_id,
            git_sha=git_sha,
            overlay=args.overlay,
            status=status,
            failure_code=failure_code,
            rendered_resource_count=rendered_resource_count,
            sampled_line_sha256=line_hashes,
            sampled_output_sha256=sampled_sha,
            rendered_manifest_sha256=manifest_sha,
            write_receipt=write_receipt,
            apply_executed=apply_executed,
        )
        try:
            output_path = _write_receipt(receipt, run_id=run_id)
            print(f"receipt: {output_path}")
        except RehearsalError as exc:
            print(f"[onprem-rehearsal] ERROR({exc.code}): {exc}")
            return 1
        except Exception as exc:  # pragma: no cover - defensive fallback
            print(f"[onprem-rehearsal] ERROR(RECEIPT_WRITE_FAILED): {exc}")
            return 1

    return 0 if status == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
