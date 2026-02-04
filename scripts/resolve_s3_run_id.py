#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from typing import Optional

try:  # pragma: no cover - exercised in integration/moto tests
    import boto3
    from botocore.exceptions import ClientError
except Exception:  # pragma: no cover
    boto3 = None
    ClientError = Exception


def _normalize_prefix(prefix: str) -> str:
    return prefix.strip("/")


def _parse_run_id(run_id: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(run_id.replace("Z", "+00:00"))
    except ValueError:
        return None


def _read_pointer(client, bucket: str, key: str) -> Optional[dict]:
    try:
        payload = client.get_object(Bucket=bucket, Key=key)["Body"].read()
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code")
        if code in {"NoSuchKey", "404"}:
            return None
        raise
    try:
        return json.loads(payload.decode("utf-8"))
    except json.JSONDecodeError:
        return None


def _has_object(client, bucket: str, key: str) -> bool:
    try:
        client.head_object(Bucket=bucket, Key=key)
        return True
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code")
        if code in {"NoSuchKey", "404"}:
            return False
        raise


def _run_report_key(prefix: str, run_id: str) -> str:
    clean = _normalize_prefix(prefix)
    return f"{clean}/runs/{run_id}/run_report.json".strip("/")


def _ranked_families_key(prefix: str, run_id: str, provider: str, profile: str) -> str:
    clean = _normalize_prefix(prefix)
    return f"{clean}/runs/{run_id}/{provider}/{profile}/{provider}_ranked_families.{profile}.json".strip("/")


def _resolve_from_pointers(
    client,
    bucket: str,
    prefix: str,
    provider: str,
    profile: str,
) -> Optional[str]:
    clean = _normalize_prefix(prefix)
    pointer_keys = [
        f"{clean}/state/{provider}/{profile}/last_success.json".strip("/"),
        f"{clean}/state/last_success.json".strip("/"),
    ]
    for key in pointer_keys:
        payload = _read_pointer(client, bucket, key)
        run_id = payload.get("run_id") if isinstance(payload, dict) else None
        if not run_id:
            continue
        report_key = _run_report_key(prefix, run_id)
        ranked_key = _ranked_families_key(prefix, run_id, provider, profile)
        if _has_object(client, bucket, report_key) and _has_object(client, bucket, ranked_key):
            return run_id
    return None


def _select_latest_run_id(
    client,
    bucket: str,
    prefix: str,
    provider: str,
    profile: str,
) -> Optional[str]:
    clean = _normalize_prefix(prefix)
    runs_prefix = f"{clean}/runs/".strip("/")
    report_suffix = "/run_report.json"
    ranked_suffix = f"/{provider}/{profile}/{provider}_ranked_families.{profile}.json"

    runs: dict[str, dict[str, object]] = {}
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=runs_prefix):
        for item in page.get("Contents", []):
            key = item["Key"]
            if not key.startswith(runs_prefix):
                continue
            rest = key[len(runs_prefix) :]
            run_id = rest.split("/", 1)[0]
            if not run_id:
                continue
            info = runs.setdefault(run_id, {"report": False, "ranked": False, "last_modified": None})
            if key.endswith(report_suffix):
                info["report"] = True
            if key.endswith(ranked_suffix):
                info["ranked"] = True
            last_modified = item.get("LastModified")
            if last_modified and (info["last_modified"] is None or last_modified > info["last_modified"]):
                info["last_modified"] = last_modified

    best_run_id = None
    best_time = None
    for run_id, info in runs.items():
        if not info["report"] or not info["ranked"]:
            continue
        candidate_time = _parse_run_id(run_id) or info["last_modified"]
        if candidate_time is None:
            continue
        if best_time is None or candidate_time > best_time:
            best_time = candidate_time
            best_run_id = run_id
    return best_run_id


def resolve_run_id(
    bucket: str,
    prefix: str,
    provider: str,
    profile: str,
    *,
    client=None,
) -> Optional[str]:
    if not bucket or not prefix:
        return None
    if client is None:
        if boto3 is None:
            raise RuntimeError("boto3 is required to resolve S3 run IDs")
        client = boto3.client("s3", region_name=os.environ.get("AWS_REGION") or "us-east-1")
    run_id = _resolve_from_pointers(client, bucket, prefix, provider, profile)
    if run_id:
        return run_id
    return _select_latest_run_id(client, bucket, prefix, provider, profile)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Resolve latest valid S3 run_id.")
    parser.add_argument("--bucket", default=os.environ.get("JOBINTEL_S3_BUCKET") or os.environ.get("BUCKET"))
    parser.add_argument(
        "--prefix",
        default=os.environ.get("JOBINTEL_S3_PREFIX") or os.environ.get("PREFIX") or "jobintel",
    )
    parser.add_argument("--provider", default=os.environ.get("PROVIDER") or "openai")
    parser.add_argument("--profile", default=os.environ.get("PROFILE") or "cs")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    bucket = args.bucket
    prefix = _normalize_prefix(args.prefix or "")
    if not bucket or not prefix:
        print("bucket and prefix are required to resolve run_id", file=sys.stderr)
        return 2
    run_id = resolve_run_id(bucket, prefix, args.provider, args.profile)
    if not run_id:
        print(
            f"no valid run_id found under s3://{bucket}/{prefix}/runs/",
            file=sys.stderr,
        )
        return 1
    print(run_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
