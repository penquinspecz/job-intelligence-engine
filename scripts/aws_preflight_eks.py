#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from typing import Dict, Optional


@dataclass
class CheckResult:
    ok: bool
    message: str


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, check=False, capture_output=True, text=True)


def _aws(cmd: list[str], region: Optional[str]) -> subprocess.CompletedProcess[str]:
    full = ["aws", *cmd]
    if region:
        full.extend(["--region", region])
    return _run(full)


def _required_env_or_arg(name: str, value: Optional[str]) -> str:
    candidate = (value or os.environ.get(name, "")).strip()
    if not candidate:
        raise ValueError(f"missing required value: {name}")
    return candidate


def _check_aws_identity(region: Optional[str]) -> CheckResult:
    res = _aws(["sts", "get-caller-identity", "--output", "json"], region)
    if res.returncode != 0:
        return CheckResult(False, res.stderr.strip() or "aws sts get-caller-identity failed")
    return CheckResult(True, "aws identity ok")


def _check_eks_cluster(cluster: str, region: str) -> CheckResult:
    res = _aws(["eks", "describe-cluster", "--name", cluster, "--output", "json"], region)
    if res.returncode != 0:
        return CheckResult(False, res.stderr.strip() or f"eks cluster not reachable: {cluster}")
    return CheckResult(True, f"eks cluster ok: {cluster}")


def _check_ecr_repo(repo: str, region: str) -> CheckResult:
    res = _aws(["ecr", "describe-repositories", "--repository-names", repo, "--output", "json"], region)
    if res.returncode != 0:
        return CheckResult(False, res.stderr.strip() or f"ecr repository not found: {repo}")
    return CheckResult(True, f"ecr repository ok: {repo}")


def _check_s3_bucket(bucket: str, region: str) -> CheckResult:
    res = _aws(["s3api", "head-bucket", "--bucket", bucket], region)
    if res.returncode != 0:
        return CheckResult(False, res.stderr.strip() or f"s3 bucket not reachable: {bucket}")
    return CheckResult(True, f"s3 bucket ok: {bucket}")


def _check_kubectl(context: Optional[str]) -> CheckResult:
    if not shutil.which("kubectl"):
        return CheckResult(False, "kubectl not found")
    if context:
        cmd = ["kubectl", "--context", context, "cluster-info"]
    else:
        cmd = ["kubectl", "cluster-info"]
    res = _run(cmd)
    if res.returncode != 0:
        return CheckResult(False, res.stderr.strip() or "kubectl cluster-info failed")
    return CheckResult(True, "kubectl context ok")


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Preflight checks for EKS + ECR golden path")
    parser.add_argument("--region", default=os.environ.get("AWS_REGION") or os.environ.get("JOBINTEL_AWS_REGION"))
    parser.add_argument("--cluster", default=os.environ.get("EKS_CLUSTER_NAME"))
    parser.add_argument("--ecr-repo", default=os.environ.get("ECR_REPO", "jobintel"))
    parser.add_argument("--bucket", default=os.environ.get("JOBINTEL_S3_BUCKET"))
    parser.add_argument("--kube-context", default=os.environ.get("KUBE_CONTEXT"))
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON output")
    args = parser.parse_args(argv)

    try:
        region = _required_env_or_arg("AWS_REGION", args.region)
        cluster = _required_env_or_arg("EKS_CLUSTER_NAME", args.cluster)
        bucket = _required_env_or_arg("JOBINTEL_S3_BUCKET", args.bucket)
        ecr_repo = _required_env_or_arg("ECR_REPO", args.ecr_repo)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    checks: Dict[str, CheckResult] = {
        "aws_identity": _check_aws_identity(region),
        "eks_cluster": _check_eks_cluster(cluster, region),
        "kubectl_context": _check_kubectl(args.kube_context),
        "ecr_repo": _check_ecr_repo(ecr_repo, region),
        "s3_bucket": _check_s3_bucket(bucket, region),
    }

    all_ok = all(item.ok for item in checks.values())
    payload = {
        "ok": all_ok,
        "region": region,
        "cluster": cluster,
        "kube_context": args.kube_context,
        "ecr_repo": ecr_repo,
        "bucket": bucket,
        "checks": {name: {"ok": cr.ok, "message": cr.message} for name, cr in checks.items()},
    }

    if args.json:
        print(json.dumps(payload, sort_keys=True))
    else:
        for name, result in checks.items():
            status = "OK" if result.ok else "FAIL"
            print(f"[{status}] {name}: {result.message}")

    return 0 if all_ok else 3


if __name__ == "__main__":
    raise SystemExit(main())
