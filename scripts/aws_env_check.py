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
from pathlib import Path
from typing import Any, Dict, List, Tuple

DEFAULT_PREFIX = "jobintel"


def _resolve_bucket(explicit: str | None) -> str | None:
    return (explicit or os.getenv("JOBINTEL_S3_BUCKET") or os.getenv("BUCKET") or "").strip() or None


def _resolve_region(explicit: str | None) -> str | None:
    return (
        (explicit or os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or os.getenv("REGION") or "")
        .strip()
        or None
    )


def _resolve_prefix(explicit: str | None) -> Tuple[str | None, List[str]]:
    warnings: List[str] = []
    prefix = (explicit or os.getenv("JOBINTEL_S3_PREFIX") or os.getenv("PREFIX") or DEFAULT_PREFIX).strip()
    prefix = prefix.strip("/")
    if not prefix:
        warnings.append("prefix resolved to empty after normalization")
        return None, warnings
    return prefix, warnings


def _credentials_from_env() -> bool:
    return bool(os.getenv("AWS_ACCESS_KEY_ID") and os.getenv("AWS_SECRET_ACCESS_KEY"))


def _credentials_from_profile() -> bool:
    profile = os.getenv("AWS_PROFILE")
    if not profile:
        return False
    shared_path = os.getenv("AWS_SHARED_CREDENTIALS_FILE")
    if shared_path:
        return Path(shared_path).expanduser().exists()
    default_path = Path.home() / ".aws" / "credentials"
    return default_path.exists()


def _credentials_from_ecs() -> bool:
    return bool(os.getenv("AWS_CONTAINER_CREDENTIALS_RELATIVE_URI") or os.getenv("AWS_CONTAINER_CREDENTIALS_FULL_URI"))


def _resolve_credentials() -> Tuple[Dict[str, Any], List[str]]:
    warnings: List[str] = []
    if _credentials_from_env():
        return {"present": True, "source": "env"}, warnings
    if _credentials_from_ecs():
        return {"present": True, "source": "ecs"}, warnings
    if _credentials_from_profile():
        return {"present": True, "source": "profile"}, warnings
    if os.getenv("AWS_EC2_METADATA_DISABLED", "").lower() != "true":
        warnings.append("credentials not detected; EC2 instance metadata may be available")
    return {"present": False, "source": "none"}, warnings


def _build_report(bucket: str | None, region: str | None, prefix: str | None) -> Dict[str, Any]:
    errors: List[str] = []
    warnings: List[str] = []

    if not bucket:
        errors.append("bucket is required (JOBINTEL_S3_BUCKET or BUCKET)")
    if not region:
        errors.append("region is required (AWS_REGION/AWS_DEFAULT_REGION/REGION)")

    credentials, cred_warnings = _resolve_credentials()
    warnings.extend(cred_warnings)
    if not credentials.get("present"):
        errors.append("credentials not detected (env/profile/ecs)")

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
