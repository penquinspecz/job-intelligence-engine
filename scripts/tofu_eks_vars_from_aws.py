#!/usr/bin/env python3
from __future__ import annotations

try:
    import _bootstrap  # type: ignore
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
EKS_DIR = REPO_ROOT / "ops" / "aws" / "infra" / "eks"
OUT_FILE = EKS_DIR / "local.auto.tfvars.json"


def _env_or_default(name: str, default: str) -> str:
    value = os.environ.get(name, "").strip()
    return value if value else default


def _require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"missing required env var: {name}")
    return value


def _run_aws(cmd: list[str]) -> dict[str, Any]:
    result = subprocess.run(["aws", *cmd], check=False, capture_output=True, text=True)
    if result.returncode != 0:
        message = result.stderr.strip() or "aws command failed"
        raise RuntimeError(message)
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"invalid aws json output: {exc}") from exc


def _bucket_name(cluster_name: str) -> tuple[str, str]:
    artifacts_bucket = os.environ.get("JOBINTEL_ARTIFACTS_BUCKET", "").strip()
    if artifacts_bucket:
        return artifacts_bucket, "JOBINTEL_ARTIFACTS_BUCKET"
    s3_bucket = os.environ.get("JOBINTEL_S3_BUCKET", "").strip()
    if s3_bucket:
        return s3_bucket, "JOBINTEL_S3_BUCKET"
    return f"{cluster_name}-artifacts", "derived default <cluster>-artifacts"


def main() -> int:
    try:
        _require_env("AWS_PROFILE")
        region = _env_or_default("AWS_REGION", _env_or_default("AWS_DEFAULT_REGION", "us-east-1"))
        cluster_name = _env_or_default("CLUSTER_NAME", "jobintel-eks")

        payload = _run_aws(
            [
                "eks",
                "describe-cluster",
                "--name",
                cluster_name,
                "--region",
                region,
                "--output",
                "json",
            ]
        )

        cluster = payload.get("cluster", {})
        vpc_config = cluster.get("resourcesVpcConfig", {})
        subnet_ids = sorted(vpc_config.get("subnetIds", []))
        vpc_id = (vpc_config.get("vpcId") or "").strip()
        if not subnet_ids:
            raise RuntimeError(f"cluster {cluster_name} returned no subnet IDs")

        s3_bucket, bucket_source = _bucket_name(cluster_name)
        vars_payload: dict[str, Any] = {
            "s3_bucket": s3_bucket,
            "subnet_ids": subnet_ids,
        }
        if vpc_id:
            vars_payload["vpc_id"] = vpc_id

        OUT_FILE.write_text(json.dumps(vars_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        print(f"Wrote {OUT_FILE}")
        print(
            "Summary: "
            f"cluster={cluster_name} region={region} "
            f"subnet_count={len(subnet_ids)} vpc_id={vpc_id or '<unknown>'} "
            f"s3_bucket_source={bucket_source}"
        )
        print(f"subnet_ids={','.join(subnet_ids)}")
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        region = _env_or_default("AWS_REGION", _env_or_default("AWS_DEFAULT_REGION", "us-east-1"))
        cluster_name = _env_or_default("CLUSTER_NAME", "jobintel-eks")
        print(
            "NEXT: "
            f"AWS_PROFILE=jobintel-deployer AWS_REGION={region} CLUSTER_NAME={cluster_name} "
            'aws eks describe-cluster --name "$CLUSTER_NAME" --region "$AWS_REGION" --output json',
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
