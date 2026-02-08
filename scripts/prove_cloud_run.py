#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional

from ji_engine.utils.time import utc_now_z

RUN_ID_REGEX = re.compile(r"jobintel start\s+([0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9:.]+Z)")
RUN_ID_KV_REGEX = re.compile(r"^JOBINTEL_RUN_ID=([0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9:.]+Z)$", re.MULTILINE)
PROVENANCE_LINE_REGEX = re.compile(r"\[run_scrape\]\[provenance\]\s+(.*)$", re.MULTILINE)
S3_STATUS_REGEX = re.compile(r"s3_status=([a-z_]+)")
PUBLISH_POINTER_REGEX = re.compile(r"PUBLISH_CONTRACT .*pointer_global=([a-z_]+)")


def _utc_now_iso() -> str:
    return utc_now_z(seconds_precision=True)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _state_dir() -> Path:
    return Path(os.environ.get("JOBINTEL_STATE_DIR", _repo_root() / "state"))


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=False, capture_output=True, text=True)


def _extract_run_id(logs: str) -> Optional[str]:
    match = RUN_ID_KV_REGEX.search(logs)
    if match:
        return match.group(1)
    match = RUN_ID_REGEX.search(logs)
    if not match:
        return None
    return match.group(1)


def _extract_provenance_line(logs: str) -> Optional[str]:
    matches = PROVENANCE_LINE_REGEX.findall(logs)
    if not matches:
        return None
    return matches[-1]


def _extract_provenance_payload(logs: str) -> Optional[dict]:
    line = _extract_provenance_line(logs)
    if not line:
        return None
    try:
        return json.loads(line)
    except json.JSONDecodeError:
        return None


def _extract_publish_markers(logs: str) -> dict:
    s3_status = None
    pointer_global = None
    s3_match = S3_STATUS_REGEX.search(logs)
    if s3_match:
        s3_status = s3_match.group(1)
    pointer_match = PUBLISH_POINTER_REGEX.search(logs)
    if pointer_match:
        pointer_global = pointer_match.group(1)
    return {"s3_status": s3_status, "pointer_global": pointer_global}


def _kubectl_logs(namespace: str, job_name: str, kube_context: Optional[str]) -> str:
    cmd = ["kubectl", "logs", f"job/{job_name}", "-n", namespace]
    if kube_context:
        cmd.extend(["--context", kube_context])
    result = _run(cmd)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "kubectl logs failed")
    return result.stdout


def _commit_sha() -> Optional[str]:
    result = _run(["git", "rev-parse", "HEAD"])
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _verify(bucket: str, prefix: str, run_id: str) -> int:
    cmd = [
        sys.executable,
        str(_repo_root() / "scripts" / "verify_published_s3.py"),
        "--bucket",
        bucket,
        "--run-id",
        run_id,
        "--prefix",
        prefix,
        "--verify-latest",
    ]
    result = _run(cmd)
    return result.returncode


def _print_next_commands(run_id: str, bucket: str, prefix: str, namespace: str, job_name: str) -> None:
    lines = [
        "Next commands:",
        f"  python scripts/verify_published_s3.py --bucket {bucket} --run-id {run_id} --prefix {prefix} --verify-latest",
        f"  cat state/proofs/{run_id}.json",
        f"  kubectl -n {namespace} logs job/{job_name}",
    ]
    print("\n".join(lines))


def _write_liveproof_log(run_id: str, logs: str) -> Optional[Path]:
    line = _extract_provenance_line(logs)
    if not line:
        return None
    proof_dir = _repo_root() / "ops" / "proof"
    proof_dir.mkdir(parents=True, exist_ok=True)
    proof_path = proof_dir / f"liveproof-{run_id}.log"
    payload = f"JOBINTEL_RUN_ID={run_id}\n{line}\n"
    proof_path.write_text(payload, encoding="utf-8")
    return proof_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Capture proof artifacts for a real cloud run.")
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--prefix", default="jobintel")
    parser.add_argument("--namespace", default="jobintel")
    parser.add_argument("--job-name", required=True)
    parser.add_argument("--kube-context", default=None)
    parser.add_argument("--run-id", default=None)
    args = parser.parse_args(argv)

    try:
        logs = _kubectl_logs(args.namespace, args.job_name, args.kube_context)
        run_id = args.run_id or _extract_run_id(logs)
        if not run_id:
            print("ERROR: run_id not provided and could not be extracted from logs", file=sys.stderr)
            return 3

        verify_code = _verify(args.bucket, args.prefix, run_id)
        verified_ok = verify_code == 0
        provenance = _extract_provenance_payload(logs)
        publish_markers = _extract_publish_markers(logs)
        liveproof_log = _write_liveproof_log(run_id, logs)
        proof = {
            "run_id": run_id,
            "cluster_context": args.kube_context,
            "namespace": args.namespace,
            "job_name": args.job_name,
            "bucket": args.bucket,
            "prefix": args.prefix,
            "verified_ok": verified_ok,
            "timestamp_utc": _utc_now_iso(),
            "commit_sha": _commit_sha(),
            "provenance": provenance,
            "publish_markers": publish_markers,
            "liveproof_log_path": str(liveproof_log) if liveproof_log else None,
        }

        proof_dir = _state_dir() / "proofs"
        proof_dir.mkdir(parents=True, exist_ok=True)
        proof_path = proof_dir / f"{run_id}.json"
        proof_path.write_text(json.dumps(proof, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        if verify_code != 0:
            print("ERROR: verify_published_s3 failed", file=sys.stderr)
            return 2
        _print_next_commands(run_id, args.bucket, args.prefix, args.namespace, args.job_name)
        return 0
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 3
    except Exception as exc:
        print(f"ERROR: {exc!r}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
