#!/usr/bin/env python3
from __future__ import annotations

try:
    import _bootstrap  # type: ignore
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

import json
import os
import sys
from typing import List, Optional

import boto3
from botocore.exceptions import ClientError

DEFAULT_PREFIX = "jobintel"


def _resolve_bucket() -> Optional[str]:
    return (os.getenv("JOBINTEL_S3_BUCKET") or os.getenv("BUCKET") or "").strip() or None


def _resolve_region() -> Optional[str]:
    return (
        os.getenv("JOBINTEL_AWS_REGION")
        or os.getenv("AWS_REGION")
        or os.getenv("AWS_DEFAULT_REGION")
        or os.getenv("REGION")
        or ""
    ).strip() or None


def _resolve_prefix() -> Optional[str]:
    prefix = (os.getenv("JOBINTEL_S3_PREFIX") or os.getenv("PREFIX") or DEFAULT_PREFIX).strip()
    prefix = prefix.strip("/")
    return prefix or None


def _print_env(bucket: Optional[str], region: Optional[str], prefix: Optional[str]) -> None:
    aws_role_arn = os.getenv("AWS_ROLE_ARN")
    token_file = os.getenv("AWS_WEB_IDENTITY_TOKEN_FILE")
    token_present = bool(token_file and os.path.exists(token_file))
    payload = {
        "bucket": bucket,
        "region": region,
        "prefix": prefix,
        "aws_role_arn_set": bool(aws_role_arn),
        "web_identity_token_file_set": bool(token_file),
        "web_identity_token_file_exists": token_present,
    }
    print(json.dumps(payload, sort_keys=True))


def _format_s3_client_error(exc: ClientError, bucket: str | None, region: str | None) -> str:
    response = exc.response or {}
    error = response.get("Error", {}) or {}
    code = str(error.get("Code", "Unknown"))
    msg = str(error.get("Message", "Unknown"))
    meta = response.get("ResponseMetadata", {}) or {}
    status = meta.get("HTTPStatusCode")
    headers = meta.get("HTTPHeaders", {}) or {}
    bucket_region = headers.get("x-amz-bucket-region")
    role = os.getenv("AWS_ROLE_ARN") or "unknown"

    if status == 404 or code in {"NoSuchBucket", "NotFound"}:
        return f"S3 bucket not found: {bucket}. Create it or verify name."
    if status == 403 or code in {"AccessDenied"}:
        return f"Access denied to bucket: {bucket}. Verify IAM policy for role {role}."
    if status == 301 or code in {"PermanentRedirect"}:
        if bucket_region:
            return f"Bucket exists in region {bucket_region}; set JOBINTEL_AWS_REGION accordingly."
        return f"S3 error {code} (HTTP {status}) for bucket {bucket}: {msg}"
    if bucket_region and region and bucket_region != region:
        return f"Bucket exists in region {bucket_region}; set JOBINTEL_AWS_REGION accordingly."
    return f"S3 error {code} (HTTP {status}) for bucket {bucket}: {msg}"


def main() -> int:
    bucket = _resolve_bucket()
    region = _resolve_region()
    prefix = _resolve_prefix()

    missing: List[str] = []
    if not bucket:
        missing.append("JOBINTEL_S3_BUCKET")
    if not region:
        missing.append("AWS_REGION/AWS_DEFAULT_REGION/JOBINTEL_AWS_REGION")

    _print_env(bucket, region, prefix)

    if missing:
        print("missing required env vars: " + ", ".join(missing), file=sys.stderr)
        return 2

    try:
        session = boto3.session.Session(region_name=region)
        sts = session.client("sts")
        s3 = session.client("s3")
        sts.get_caller_identity()
        s3.head_bucket(Bucket=bucket)
        if prefix:
            s3.list_objects_v2(Bucket=bucket, Prefix=prefix, MaxKeys=5)
        print("s3_preflight: ok")
        return 0
    except ClientError as exc:
        print(_format_s3_client_error(exc, bucket, region), file=sys.stderr)
        return 3
    except Exception as exc:
        print(f"aws client error: {exc.__class__.__name__}: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
