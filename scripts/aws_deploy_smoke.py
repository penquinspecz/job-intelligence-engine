#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path
from typing import Iterable

import boto3
from botocore.exceptions import ClientError

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def _parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bucket", default=os.environ.get("JOBINTEL_S3_BUCKET", ""))
    ap.add_argument("--prefix", default=os.environ.get("JOBINTEL_S3_PREFIX", "jobintel"))
    ap.add_argument("--require", action="store_true", help="Exit non-zero if checks fail")
    return ap.parse_args()


def _check_identity() -> bool:
    try:
        sts = boto3.client("sts")
        ident = sts.get_caller_identity()
        logger.info("AWS identity: %s", ident.get("Arn"))
        return True
    except Exception as exc:
        logger.error("STS get-caller-identity failed: %r", exc)
        return False


def _check_bucket(bucket: str, prefix: str) -> bool:
    s3 = boto3.client("s3")
    try:
        s3.head_bucket(Bucket=bucket)
    except ClientError as exc:
        logger.error("Bucket access failed: %s", exc)
        return False

    try:
        s3.list_objects_v2(Bucket=bucket, Prefix=prefix, MaxKeys=1)
    except ClientError as exc:
        logger.error("Prefix list failed: %s", exc)
        return False

    logger.info("Bucket OK: s3://%s/%s", bucket, prefix)
    return True


def _print_expected_paths(bucket: str, prefix: str) -> None:
    clean = prefix.strip("/")
    logger.info("Expected keys:")
    logger.info("  s3://%s/%s/runs/<run_id>/...", bucket, clean)
    logger.info("  s3://%s/%s/latest/<provider>/<profile>/...", bucket, clean)


def _find_plaintext_secrets(taskdef: dict, names: Iterable[str]) -> list[str]:
    found: list[str] = []
    targets = {name.upper() for name in names}
    containers = taskdef.get("containerDefinitions", [])
    if not isinstance(containers, list):
        return found
    for container in containers:
        env = container.get("environment", [])
        if not isinstance(env, list):
            continue
        for entry in env:
            if not isinstance(entry, dict):
                continue
            name = (entry.get("name") or "").upper()
            if name in targets:
                found.append(name)
    return sorted(set(found))


def _warn_plaintext_secrets(taskdef_path: Path) -> None:
    if not taskdef_path.exists():
        return
    try:
        payload = json.loads(taskdef_path.read_text(encoding="utf-8"))
    except Exception:
        logger.warning("Could not parse task definition: %s", taskdef_path)
        return
    names = _find_plaintext_secrets(payload, ["OPENAI_API_KEY", "DISCORD_WEBHOOK_URL"])
    if names:
        logger.warning(
            "Plaintext secrets found in task definition env: %s. Use container_secrets with SSM/Secrets Manager.",
            ", ".join(names),
        )


def main() -> int:
    args = _parse_args()
    bucket = args.bucket
    prefix = args.prefix or "jobintel"
    ok = True

    if not bucket:
        logger.error("Missing bucket (set JOBINTEL_S3_BUCKET or pass --bucket)")
        ok = False
    if ok:
        ok = _check_identity() and _check_bucket(bucket, prefix)
        _print_expected_paths(bucket, prefix)
    taskdef_path = Path(os.environ.get("JOBINTEL_TASKDEF_PATH", "ops/aws/ecs-taskdef.json"))
    _warn_plaintext_secrets(taskdef_path)
    if not ok and args.require:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
