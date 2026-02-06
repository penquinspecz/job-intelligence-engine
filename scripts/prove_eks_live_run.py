#!/usr/bin/env python3
from __future__ import annotations

try:
    import _bootstrap  # type: ignore
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ji_engine.proof.liveproof import (
    build_liveproof_capture,
    extract_provenance_line,
    extract_provenance_payload,
    extract_publish_markers,
    extract_run_id,
    required_provenance_issues,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, check=False, text=True, capture_output=True)


def _kubectl_cmd(context: Optional[str], *args: str) -> list[str]:
    cmd = ["kubectl"]
    if context:
        cmd.extend(["--context", context])
    cmd.extend(args)
    return cmd


def _run_checked(cmd: list[str], *, step: str) -> str:
    result = _run(cmd)
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "command failed"
        raise RuntimeError(f"{step} failed: {detail}")
    return result.stdout


def _parse_namespace(args: argparse.Namespace) -> str:
    return args.namespace.strip()


def _copy_proof_json(context: Optional[str], namespace: str, pod_name: str, run_id: str) -> Path:
    local = REPO_ROOT / "state" / "proofs" / f"{run_id}.json"
    remote = f"{pod_name}:/app/state/proofs/{run_id}.json"
    local.parent.mkdir(parents=True, exist_ok=True)
    cmd = _kubectl_cmd(context, "-n", namespace, "cp", remote, str(local))
    _run_checked(cmd, step="copy proof json")
    return local


def _write_liveproof_log(run_id: str, logs: str, provenance_line: str, publish_line: str) -> Path:
    path = REPO_ROOT / "ops" / "proof" / f"liveproof-{run_id}.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    tail = "\n".join(logs.splitlines()[-120:])
    payload = [
        f"JOBINTEL_RUN_ID={run_id}",
        f"[run_scrape][provenance] {provenance_line}",
        publish_line,
        "",
        "--- LOG TAIL ---",
        tail,
        "",
    ]
    path.write_text("\n".join(payload), encoding="utf-8")
    return path


def _write_verify_log(run_id: str, verify_cmd: list[str], verify_result: subprocess.CompletedProcess[str]) -> Path:
    path = REPO_ROOT / "ops" / "proof" / f"verify_published_s3-{run_id}.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(
        [
            f"command: {' '.join(verify_cmd)}",
            f"exit_code: {verify_result.returncode}",
            "--- stdout ---",
            verify_result.stdout,
            "--- stderr ---",
            verify_result.stderr,
            "",
        ]
    )
    path.write_text(text, encoding="utf-8")
    return path


def _extract_publish_line(logs: str) -> str:
    for line in reversed(logs.splitlines()):
        if "PUBLISH_CONTRACT " in line:
            return line
    return ""


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run one-off EKS liveproof job and capture deterministic receipts.")
    parser.add_argument("--cluster-name", required=True)
    parser.add_argument("--namespace", default="jobintel")
    parser.add_argument("--context", default=None)
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--prefix", default="jobintel")
    parser.add_argument("--timeout", default="20m")
    args = parser.parse_args(argv)

    namespace = _parse_namespace(args)
    ts = _utc_stamp()
    job_name = f"jobintel-liveproof-{ts}"

    try:
        create_cmd = _kubectl_cmd(
            args.context,
            "-n",
            namespace,
            "create",
            "job",
            "--from=cronjob/jobintel-daily",
            job_name,
        )
        _run_checked(create_cmd, step="create liveproof job")

        set_env_cmd = _kubectl_cmd(
            args.context,
            "-n",
            namespace,
            "set",
            "env",
            f"job/{job_name}",
            "CAREERS_MODE=LIVE",
            "JOBINTEL_WRITE_PROOF=1",
            "PUBLISH_S3=1",
            "PUBLISH_S3_DRY_RUN=0",
            "PUBLISH_S3_REQUIRE=1",
        )
        _run_checked(set_env_cmd, step="set liveproof env")

        set_args_cmd = _kubectl_cmd(
            args.context,
            "-n",
            namespace,
            "set",
            "args",
            f"job/{job_name}",
            "--",
            "python",
            "scripts/run_daily.py",
            "--profiles",
            "cs",
            "--us_only",
            "--no_post",
        )
        _run_checked(set_args_cmd, step="set liveproof args")

        wait_cmd = _kubectl_cmd(
            args.context,
            "-n",
            namespace,
            "wait",
            "--for=condition=complete",
            f"job/{job_name}",
            f"--timeout={args.timeout}",
        )
        _run_checked(wait_cmd, step="wait for completion")

        pod_name = _run_checked(
            _kubectl_cmd(
                args.context,
                "-n",
                namespace,
                "get",
                "pods",
                "-l",
                f"job-name={job_name}",
                "-o",
                "jsonpath={.items[0].metadata.name}",
            ),
            step="resolve pod name",
        ).strip()
        image = _run_checked(
            _kubectl_cmd(
                args.context,
                "-n",
                namespace,
                "get",
                "pod",
                pod_name,
                "-o",
                "jsonpath={.spec.containers[0].image}",
            ),
            step="resolve pod image",
        ).strip()
        logs = _run_checked(_kubectl_cmd(args.context, "-n", namespace, "logs", f"job/{job_name}"), step="fetch logs")

        run_id = extract_run_id(logs)
        if not run_id:
            raise RuntimeError("missing JOBINTEL_RUN_ID in logs")
        provenance_payload = extract_provenance_payload(logs)
        provenance_line = extract_provenance_line(logs)
        if not provenance_payload or not provenance_line:
            raise RuntimeError("missing [run_scrape][provenance] JSON line in logs")
        issues = required_provenance_issues(provenance_payload)
        if issues:
            raise RuntimeError("; ".join(issues))
        publish_markers = extract_publish_markers(logs)
        if publish_markers.get("s3_status") != "ok":
            raise RuntimeError("missing s3_status=ok in logs")
        if publish_markers.get("pointer_global") != "ok":
            raise RuntimeError("missing pointer_global=ok in logs")
        publish_line = _extract_publish_line(logs)
        if not publish_line:
            raise RuntimeError("missing PUBLISH_CONTRACT log line")

        liveproof_log_path = _write_liveproof_log(run_id, logs, provenance_line, publish_line)
        proof_json_path = _copy_proof_json(args.context, namespace, pod_name, run_id)

        verify_cmd = [
            sys.executable,
            str(REPO_ROOT / "scripts" / "verify_published_s3.py"),
            "--bucket",
            args.bucket,
            "--run-id",
            run_id,
            "--prefix",
            args.prefix,
            "--verify-latest",
        ]
        verify_result = _run(verify_cmd)
        verify_log_path = _write_verify_log(run_id, verify_cmd, verify_result)
        if verify_result.returncode != 0:
            raise RuntimeError("verify_published_s3 failed")

        base_payload = json.loads(proof_json_path.read_text(encoding="utf-8"))
        if not isinstance(base_payload, dict):
            raise RuntimeError("proof json from pod is not an object")
        base_payload["liveproof_capture"] = build_liveproof_capture(
            run_id=run_id,
            cluster_name=args.cluster_name,
            namespace=namespace,
            job_name=job_name,
            pod_name=pod_name,
            image=image,
            bucket=args.bucket,
            prefix=args.prefix,
            verify_exit_code=verify_result.returncode,
            verify_log_path=str(verify_log_path),
            liveproof_log_path=str(liveproof_log_path),
            provenance=provenance_payload,
            publish_markers=publish_markers,
        )
        proof_json_path.write_text(
            json.dumps(base_payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )

        print(f"job_name={job_name}")
        print(f"pod_name={pod_name}")
        print(f"image={image}")
        print(f"JOBINTEL_RUN_ID={run_id}")
        print(f"liveproof_log={liveproof_log_path}")
        print(f"proof_json={proof_json_path}")
        print(f"verify_log={verify_log_path}")
        print("liveproof_status=ok")
        return 0
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
