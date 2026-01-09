#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import List

import boto3
from botocore.exceptions import ClientError

from ji_engine.config import HISTORY_DIR, RUN_METADATA_DIR

logger = logging.getLogger(__name__)


def _sanitize_run_id(run_id: str) -> str:
    return run_id.replace(":", "").replace("-", "").replace(".", "")


def _history_run_dir(run_id: str, profile: str) -> Path:
    run_date = run_id.split("T")[0]
    return HISTORY_DIR / run_date / _sanitize_run_id(run_id) / profile


def _latest_profile_dir(profile: str) -> Path:
    return HISTORY_DIR / "latest" / profile


def _list_meta_runs(profile: str) -> List[dict]:
    entries = []
    for path in RUN_METADATA_DIR.glob("*.json"):
        data = path.read_text()
        payload = json.loads(data)
        if profile in (payload.get("profiles") or []):
            entries.append(payload)
    return sorted(entries, key=lambda item: item["run_id"])


def _select_run_id(profile: str, run_id: str | None, latest: bool) -> str:
    if latest and run_id:
        raise SystemExit("cannot specify --run_id and --latest together")
    if latest:
        runs = _list_meta_runs(profile)
        if not runs:
            raise SystemExit("no runs recorded yet")
        return runs[-1]["run_id"]
    if run_id:
        return run_id
    runs = _list_meta_runs(profile)
    if not runs:
        raise SystemExit("no runs recorded yet")
    return runs[-1]["run_id"]


def _collect_artifacts(base_dir: Path) -> List[Path]:
    if not base_dir.exists():
        return []
    files = sorted(p for p in base_dir.rglob("*") if p.is_file())
    for path in files:
        try:
            path.relative_to(HISTORY_DIR)
        except ValueError:
            raise SystemExit(f"artifact {path} is outside state/history and cannot be published")
    return files


def _upload_files(
    bucket: str,
    prefix: str,
    files: List[Path],
    dry_run: bool,
) -> None:
    prefix = prefix.rstrip("/")
    client = boto3.client("s3")
    for path in files:
        rel = path.relative_to(HISTORY_DIR)
        key = f"{prefix}/{rel.as_posix()}"
        if dry_run:
            logger.info("dry-run: %s -> s3://%s/%s", path, bucket, key)
            continue
        try:
            client.upload_file(str(path), bucket, key)
            logger.info("uploaded %s -> s3://%s/%s", path, bucket, key)
        except ClientError as exc:
            logger.error("upload failed: %s", exc)
            raise


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bucket", required=True)
    ap.add_argument("--prefix", default="jobintel")
    ap.add_argument("--profile", default="cs")
    ap.add_argument("--run_id")
    ap.add_argument("--latest", action="store_true")
    ap.add_argument("--dry_run", action="store_true")
    args = ap.parse_args()

    run_id = _select_run_id(args.profile, args.run_id, args.latest)
    base_dir = _history_run_dir(run_id, args.profile)
    files = _collect_artifacts(base_dir)
    if not files:
        logger.error("no artifacts found for %s/%s", run_id, args.profile)
        return 1
    _upload_files(args.bucket, args.prefix, files, args.dry_run)
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    raise SystemExit(main())
