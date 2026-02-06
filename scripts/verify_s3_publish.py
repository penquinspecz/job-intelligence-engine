#!/usr/bin/env python3
from __future__ import annotations

try:
    import _bootstrap  # type: ignore
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

import json
import os
import sys
from typing import List

import boto3
from botocore.exceptions import ClientError

DEFAULT_PREFIX = "jobintel"

REQUIRED_KEYS = [
    "openai_ranked_jobs.cs.json",
    "openai_ranked_jobs.cs.csv",
    "openai_ranked_families.cs.json",
    "openai_shortlist.cs.md",
    "openai_top.cs.md",
]


def _resolve_env() -> tuple[str | None, str | None, str | None]:
    bucket = (os.getenv("JOBINTEL_S3_BUCKET") or "").strip() or None
    prefix = (os.getenv("JOBINTEL_S3_PREFIX") or DEFAULT_PREFIX).strip().strip("/") or None
    region = (
        os.getenv("JOBINTEL_AWS_REGION") or os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or ""
    ).strip() or None
    return bucket, prefix, region


def _get_json(client, bucket: str, key: str) -> dict:
    resp = client.get_object(Bucket=bucket, Key=key)
    data = resp["Body"].read()
    return json.loads(data.decode("utf-8"))


def _head(client, bucket: str, key: str) -> None:
    client.head_object(Bucket=bucket, Key=key)


def main() -> int:
    bucket, prefix, region = _resolve_env()
    missing: List[str] = []
    if not bucket:
        missing.append("JOBINTEL_S3_BUCKET")
    if not region:
        missing.append("JOBINTEL_AWS_REGION/AWS_REGION/AWS_DEFAULT_REGION")
    if missing:
        print("missing required env vars: " + ", ".join(missing), file=sys.stderr)
        return 2

    session = boto3.session.Session(region_name=region)
    client = session.client("s3")

    pointer_key = f"{prefix}/state/last_success.json"
    try:
        pointer = _get_json(client, bucket, pointer_key)
    except ClientError as exc:
        print(f"failed to fetch last_success.json: {exc}", file=sys.stderr)
        return 3

    run_id = pointer.get("run_id")
    if not run_id:
        print("last_success.json missing run_id", file=sys.stderr)
        return 3

    required = []
    for base in (
        f"{prefix}/latest/openai/cs",
        f"{prefix}/runs/{run_id}/openai/cs",
    ):
        for name in REQUIRED_KEYS:
            required.append(f"{base}/{name}")

    try:
        for key in required:
            _head(client, bucket, key)
    except ClientError as exc:
        print(f"missing key or access error: {exc}", file=sys.stderr)
        return 3

    print("verify_s3_publish: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
