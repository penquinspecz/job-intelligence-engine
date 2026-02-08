#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from ji_engine.proof.bundle import redact_text, sha256_file  # noqa: E402
from ji_engine.utils.time import utc_now_z  # noqa: E402


def _utc_now_iso() -> str:
    return utc_now_z(seconds_precision=True)


def _run(cmd: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        check=False,
        cwd=str(cwd or REPO_ROOT),
        capture_output=True,
        text=True,
    )


def _fmt_cmd(cmd: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in cmd)


def _write_redacted(path: Path, text: str) -> None:
    path.write_text(redact_text(text), encoding="utf-8")


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_manifest(infra_dir: Path, *, run_id: str) -> Path:
    files = [p for p in sorted(infra_dir.glob("*")) if p.is_file() and p.name != "manifest.json"]
    manifest = {
        "schema_version": 1,
        "run_id": run_id,
        "files": [
            {
                "path": file_path.name,
                "sha256": sha256_file(file_path),
                "size_bytes": file_path.stat().st_size,
            }
            for file_path in files
        ],
    }
    manifest_path = infra_dir / "manifest.json"
    _write_json(manifest_path, manifest)
    return manifest_path


def _build_plan_payload(
    *,
    run_id: str,
    captured_at: str,
    k8s_context: str | None,
    namespace: str,
    terraform_apply_log: str,
    job_name: str,
    pod_name: str,
    output_dir: Path,
) -> dict:
    return {
        "schema_version": 1,
        "mode": "plan",
        "run_id": run_id,
        "captured_at": captured_at,
        "k8s_context": k8s_context or "<current-context>",
        "namespace": namespace,
        "job_name": job_name or "<latest-job>",
        "pod_name": pod_name or "<pod-from-job>",
        "terraform_apply_log": terraform_apply_log or "<optional-existing-terraform-apply-log>",
        "output_dir": str(output_dir),
        "commands": {
            "terraform": [
                "terraform -chdir=ops/aws/infra/eks output -json",
                "terraform -chdir=ops/aws/infra/eks state list",
            ],
            "kubernetes": [
                f"kubectl -n {namespace} get jobs,pods -o wide",
                f"kubectl -n {namespace} describe pod <pod-name>",
                f"kubectl -n {namespace} get events --sort-by=.metadata.creationTimestamp",
            ],
        },
        "expected_files": [
            "terraform_evidence.log",
            "kubectl_describe_pod.log",
            "kubectl_get_events.log",
            "receipt.json",
            "manifest.json",
        ],
    }


def _resolve_context(explicit_context: str | None) -> str | None:
    if explicit_context:
        return explicit_context
    current = _run(["kubectl", "config", "current-context"])
    if current.returncode != 0:
        return None
    value = current.stdout.strip()
    return value or None


def _kubectl_base(context: str | None, namespace: str) -> list[str]:
    cmd = ["kubectl"]
    if context:
        cmd.extend(["--context", context])
    cmd.extend(["-n", namespace])
    return cmd


def _latest_job_name(context: str | None, namespace: str) -> str:
    cmd = _kubectl_base(context, namespace) + [
        "get",
        "jobs",
        "--sort-by=.metadata.creationTimestamp",
        "-o",
        "custom-columns=NAME:.metadata.name",
        "--no-headers",
    ]
    result = _run(cmd)
    if result.returncode != 0:
        raise RuntimeError(f"failed to list jobs: {result.stderr.strip()}")
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError("no jobs found in namespace")
    return lines[-1]


def _pod_for_job(context: str | None, namespace: str, job_name: str) -> str:
    cmd = _kubectl_base(context, namespace) + [
        "get",
        "pods",
        "-l",
        f"job-name={job_name}",
        "--sort-by=.metadata.creationTimestamp",
        "-o",
        "custom-columns=NAME:.metadata.name",
        "--no-headers",
    ]
    result = _run(cmd)
    if result.returncode != 0:
        raise RuntimeError(f"failed to list pods for job {job_name}: {result.stderr.strip()}")
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError(f"no pods found for job {job_name}")
    return lines[-1]


def _run_checked(cmd: list[str], *, cwd: Path | None = None) -> str:
    result = _run(cmd, cwd=cwd)
    header = f"$ {_fmt_cmd(cmd)}\n"
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(f"command failed ({result.returncode}): {_fmt_cmd(cmd)} :: {detail}")
    return header + result.stdout


def _capture_execute(
    *,
    infra_dir: Path,
    run_id: str,
    captured_at: str,
    namespace: str,
    explicit_context: str | None,
    job_name: str,
    pod_name: str,
    terraform_apply_log: str,
) -> dict:
    context = _resolve_context(explicit_context)
    resolved_job = job_name or _latest_job_name(context, namespace)
    resolved_pod = pod_name or _pod_for_job(context, namespace, resolved_job)

    terraform_chunks: list[str] = []
    if terraform_apply_log:
        source = (
            (REPO_ROOT / terraform_apply_log).resolve()
            if not Path(terraform_apply_log).is_absolute()
            else Path(terraform_apply_log)
        )
        if not source.exists():
            raise RuntimeError(f"--terraform-apply-log does not exist: {source}")
        terraform_chunks.append(f"$ cat {source}\n")
        terraform_chunks.append(source.read_text(encoding="utf-8"))
        terraform_chunks.append("\n")
    terraform_chunks.append(_run_checked(["terraform", "-chdir=ops/aws/infra/eks", "output", "-json"]))
    terraform_chunks.append(_run_checked(["terraform", "-chdir=ops/aws/infra/eks", "state", "list"]))
    terraform_log = "".join(terraform_chunks)
    _write_redacted(infra_dir / "terraform_evidence.log", terraform_log)

    get_jobs_pods = _run_checked(_kubectl_base(context, namespace) + ["get", "jobs,pods", "-o", "wide"])
    describe_pod = _run_checked(_kubectl_base(context, namespace) + ["describe", "pod", resolved_pod])
    _write_redacted(infra_dir / "kubectl_describe_pod.log", get_jobs_pods + "\n" + describe_pod)

    events_log = _run_checked(
        _kubectl_base(context, namespace) + ["get", "events", "--sort-by=.metadata.creationTimestamp"]
    )
    _write_redacted(infra_dir / "kubectl_get_events.log", events_log)

    evidence_files = [
        "terraform_evidence.log",
        "kubectl_describe_pod.log",
        "kubectl_get_events.log",
    ]
    receipt = {
        "schema_version": 1,
        "run_id": run_id,
        "captured_at": captured_at,
        "mode": "execute",
        "k8s_context": context,
        "namespace": namespace,
        "job_name": resolved_job,
        "pod_name": resolved_pod,
        "evidence_files": evidence_files,
    }
    _write_json(infra_dir / "receipt.json", receipt)
    _write_manifest(infra_dir, run_id=run_id)
    return receipt


def _capture_plan(
    *,
    infra_dir: Path,
    run_id: str,
    captured_at: str,
    namespace: str,
    k8s_context: str | None,
    job_name: str,
    pod_name: str,
    terraform_apply_log: str,
) -> dict:
    plan = _build_plan_payload(
        run_id=run_id,
        captured_at=captured_at,
        k8s_context=k8s_context,
        namespace=namespace,
        terraform_apply_log=terraform_apply_log,
        job_name=job_name,
        pod_name=pod_name,
        output_dir=infra_dir,
    )
    plan_text = json.dumps(plan, indent=2, sort_keys=True) + "\n"
    _write_redacted(infra_dir / "terraform_evidence.log", plan_text)
    _write_redacted(infra_dir / "kubectl_describe_pod.log", plan_text)
    _write_redacted(infra_dir / "kubectl_get_events.log", plan_text)

    receipt = {
        "schema_version": 1,
        "run_id": run_id,
        "captured_at": captured_at,
        "mode": "plan",
        "k8s_context": k8s_context,
        "namespace": namespace,
        "job_name": job_name or "<latest-job>",
        "pod_name": pod_name or "<pod-from-job>",
        "evidence_files": [
            "terraform_evidence.log",
            "kubectl_describe_pod.log",
            "kubectl_get_events.log",
        ],
    }
    _write_json(infra_dir / "receipt.json", receipt)
    _write_manifest(infra_dir, run_id=run_id)
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Capture Milestone 3 infra receipts (Terraform + ECR pull evidence) into proof bundle."
    )
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output-dir", default="ops/proof/bundles")
    parser.add_argument("--cluster-context", default="")
    parser.add_argument("--namespace", default="jobintel")
    parser.add_argument("--job-name", default="")
    parser.add_argument("--pod-name", default="")
    parser.add_argument("--terraform-apply-log", default="")
    parser.add_argument("--execute", action="store_true", help="Run live terraform/kubectl evidence commands.")
    parser.add_argument("--plan", action="store_true", help="Explicit no-op mode (default behavior).")
    parser.add_argument("--captured-at", default="", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    output_root = (REPO_ROOT / args.output_dir).resolve()
    infra_dir = output_root / f"m3-{args.run_id}" / "infra"
    infra_dir.mkdir(parents=True, exist_ok=True)
    captured_at = args.captured_at or _utc_now_iso()

    try:
        if args.execute:
            receipt = _capture_execute(
                infra_dir=infra_dir,
                run_id=args.run_id,
                captured_at=captured_at,
                namespace=args.namespace,
                explicit_context=args.cluster_context or None,
                job_name=args.job_name,
                pod_name=args.pod_name,
                terraform_apply_log=args.terraform_apply_log,
            )
            status = "executed"
        else:
            receipt = _capture_plan(
                infra_dir=infra_dir,
                run_id=args.run_id,
                captured_at=captured_at,
                namespace=args.namespace,
                k8s_context=args.cluster_context or None,
                job_name=args.job_name,
                pod_name=args.pod_name,
                terraform_apply_log=args.terraform_apply_log,
            )
            status = "planned"
    except Exception as exc:
        print(f"capture_m3_infra_receipts_status=failed error={exc!r}")
        return 2

    print(f"capture_m3_infra_receipts_mode={receipt['mode']}")
    print(f"capture_m3_infra_receipts_run_id={args.run_id}")
    print(f"capture_m3_infra_receipts_bundle={infra_dir}")
    print(f"capture_m3_infra_receipts_receipt={infra_dir / 'receipt.json'}")
    print(f"capture_m3_infra_receipts_manifest={infra_dir / 'manifest.json'}")
    print(f"capture_m3_infra_receipts_status={status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
