#!/usr/bin/env python3
from __future__ import annotations

try:
    import _bootstrap  # type: ignore
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Tuple

import boto3
from botocore.exceptions import ClientError

DEFAULT_PREFIX = "jobintel"


def _resolve_bucket(explicit: str | None) -> str | None:
    return (explicit or os.getenv("JOBINTEL_S3_BUCKET") or os.getenv("BUCKET") or "").strip() or None


def _resolve_region(explicit: str | None) -> str | None:
    return (
        explicit
        or os.getenv("JOBINTEL_AWS_REGION")
        or os.getenv("AWS_REGION")
        or os.getenv("AWS_DEFAULT_REGION")
        or os.getenv("REGION")
        or ""
    ).strip() or None


def _resolve_prefix(explicit: str | None) -> Tuple[str | None, List[str]]:
    warnings: List[str] = []
    prefix = (explicit or os.getenv("JOBINTEL_S3_PREFIX") or os.getenv("PREFIX") or DEFAULT_PREFIX).strip()
    prefix = prefix.strip("/")
    if not prefix:
        warnings.append("prefix resolved to empty after normalization")
        return None, warnings
    return prefix, warnings


def _resolve_credentials(region: str | None) -> Tuple[Dict[str, Any], List[str], List[str]]:
    warnings: List[str] = []
    errors: List[str] = []
    session = boto3.session.Session()
    creds = session.get_credentials()
    if creds is None:
        errors.append("credentials not detected (boto3 session)")
        return {"present": False, "source": "none", "validated": False}, warnings, errors
    source = getattr(creds, "method", None) or "boto3"
    validated = False
    if region:
        try:
            sts = session.client("sts", region_name=region)
            sts.get_caller_identity()
            validated = True
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "Unknown")
            msg = exc.response.get("Error", {}).get("Message", "Unknown")
            errors.append(f"credentials validation failed ({code}): {msg}")
        except Exception as exc:  # pragma: no cover - defensive
            errors.append(f"credentials validation failed: {exc.__class__.__name__}: {exc}")
    else:
        warnings.append("region not resolved; skipping sts.get_caller_identity")
    return {"present": True, "source": source, "validated": validated}, warnings, errors


def _build_report(bucket: str | None, region: str | None, prefix: str | None) -> Dict[str, Any]:
    errors: List[str] = []
    warnings: List[str] = []

    if not bucket:
        errors.append("bucket is required (JOBINTEL_S3_BUCKET or BUCKET)")
    if not region:
        errors.append("region is required (AWS_REGION/AWS_DEFAULT_REGION/REGION)")

    credentials, cred_warnings, cred_errors = _resolve_credentials(region)
    warnings.extend(cred_warnings)
    errors.extend(cred_errors)

    resolved = {
        "bucket": bucket,
        "region": region,
        "prefix": prefix,
        "credentials": credentials,
    }
    return {"ok": len(errors) == 0, "errors": errors, "warnings": warnings, "resolved": resolved}


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AWS publish preflight checks (offline-safe).")
    parser.add_argument("--bucket", help="S3 bucket name (overrides env).")
    parser.add_argument("--region", help="AWS region (overrides env).")
    parser.add_argument("--prefix", help="S3 prefix (overrides env).")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    args = parser.parse_args(argv)

    try:
        bucket = _resolve_bucket(args.bucket)
        region = _resolve_region(args.region)
        prefix, prefix_warnings = _resolve_prefix(args.prefix)
        report = _build_report(bucket, region, prefix)
        report["warnings"].extend(prefix_warnings)
    except Exception as exc:
        payload = {"ok": False, "errors": [f"runtime error: {exc}"], "warnings": [], "resolved": {}}
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print("ERROR: runtime error during env check", file=sys.stderr)
            print(str(exc), file=sys.stderr)
        return 3

    if args.json:
        print(json.dumps(report, sort_keys=True))
    else:
        status = "OK" if report["ok"] else "FAIL"
        print(f"AWS ENV CHECK: {status}")
        for err in report["errors"]:
            print(f"error: {err}", file=sys.stderr)
        for warn in report["warnings"]:
            print(f"warn: {warn}", file=sys.stderr)
        resolved = report["resolved"]
        print(f"bucket: {resolved.get('bucket')}")
        print(f"region: {resolved.get('region')}")
        print(f"prefix: {resolved.get('prefix')}")
        creds = resolved.get("credentials") or {}
        print(f"credentials: present={creds.get('present')} source={creds.get('source')}")

    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
