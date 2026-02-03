#!/usr/bin/env python3
from __future__ import annotations

try:
    import _bootstrap  # type: ignore
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

import argparse
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

import boto3
from botocore.exceptions import ClientError

from ji_engine.config import DATA_DIR, RUN_METADATA_DIR
from ji_engine.utils.verification import compute_sha256_file

try:
    from scripts import publish_s3  # type: ignore
except ModuleNotFoundError:
    import importlib.util

    _spec = importlib.util.spec_from_file_location(
        "publish_s3", Path(__file__).with_name("publish_s3.py")
    )
    if not _spec or not _spec.loader:
        raise
    publish_s3 = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(publish_s3)


def _run_dir(run_id: str) -> Path:
    return RUN_METADATA_DIR / publish_s3._sanitize_run_id(run_id)


def _load_run_report(run_id: str, run_dir: Path | None) -> Dict[str, Any]:
    run_dir = run_dir or _run_dir(run_id)
    report_path = run_dir / "run_report.json"
    if not report_path.exists():
        raise SystemExit(2)
    data = json.loads(report_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit(2)
    return data


def _collect_verifiable(report: Dict[str, Any]) -> Dict[str, Dict[str, str]]:
    verifiable = report.get("verifiable_artifacts")
    if not isinstance(verifiable, dict) or not verifiable:
        raise SystemExit(2)
    return verifiable


def _plan_entries_from_report(
    *,
    run_id: str,
    run_dir: Path,
    prefix: str,
    verify_latest: bool,
    allow_missing: bool,
) -> List[Dict[str, Any]]:
    publish_s3.DATA_DIR = DATA_DIR
    report = _load_run_report(run_id, run_dir)
    verifiable = _collect_verifiable(report)
    plan, _latest = publish_s3._build_upload_plan(
        run_id=run_id,
        run_dir=run_dir,
        prefix=prefix,
        verifiable=verifiable,
        providers=[],
        profiles=[],
        allow_missing=allow_missing,
    )
    entries = publish_s3._build_plan_entries(run_dir=run_dir, uploads=plan, verifiable=verifiable)
    if verify_latest:
        return entries
    return [entry for entry in entries if entry.get("kind") == "runs"]


def _plan_bytes(entries: List[Dict[str, Any]]) -> bytes:
    return json.dumps(entries, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _load_plan_entries(
    *,
    run_id: str,
    run_dir: Path,
    prefix: str,
    verify_latest: bool,
    plan_json: str | None,
    allow_missing: bool,
) -> List[Dict[str, Any]]:
    if plan_json:
        payload = json.loads(Path(plan_json).read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise SystemExit(2)
        return payload
    entries = _plan_entries_from_report(
        run_id=run_id,
        run_dir=run_dir,
        prefix=prefix,
        verify_latest=verify_latest,
        allow_missing=allow_missing,
    )
    if _plan_bytes(entries) != _plan_bytes(
        _plan_entries_from_report(
            run_id=run_id,
            run_dir=run_dir,
            prefix=prefix,
            verify_latest=verify_latest,
            allow_missing=allow_missing,
        )
    ):
        raise SystemExit(2)
    return entries


def _resolve_local_path(local_path: str) -> Path:
    path = Path(local_path)
    if path.is_absolute():
        return path
    return DATA_DIR / path


def _verify_offline(entries: List[Dict[str, Any]]) -> Tuple[bool, List[str], List[str]]:
    missing: List[str] = []
    mismatched: List[str] = []
    for entry in entries:
        local_path = entry.get("local_path")
        expected_sha = entry.get("sha256")
        expected_bytes = entry.get("bytes")
        if not local_path:
            mismatched.append("missing local_path")
            continue
        path = _resolve_local_path(str(local_path))
        if not path.exists():
            missing.append(str(local_path))
            continue
        if not isinstance(expected_bytes, int):
            mismatched.append(str(local_path))
            continue
        if path.stat().st_size != expected_bytes:
            mismatched.append(str(local_path))
            continue
        if expected_sha and compute_sha256_file(path) != expected_sha:
            mismatched.append(str(local_path))
    return len(missing) == 0 and len(mismatched) == 0, missing, mismatched


def _head_object(client, bucket: str, key: str) -> Dict[str, Any] | None:
    try:
        return client.head_object(Bucket=bucket, Key=key)
    except ClientError:
        return None


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify published S3 artifacts against run_report.json.")
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-dir")
    parser.add_argument("--prefix", default="jobintel")
    parser.add_argument("--region")
    parser.add_argument("--verify-latest", action="store_true")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--plan-json")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    start = time.time()
    try:
        run_dir = Path(args.run_dir) if args.run_dir else _run_dir(args.run_id)
        entries = _load_plan_entries(
            run_id=args.run_id,
            run_dir=run_dir,
            prefix=args.prefix,
            verify_latest=bool(args.verify_latest),
            plan_json=args.plan_json,
            allow_missing=bool(args.offline),
        )
        missing: List[str] = []
        mismatched: List[str] = []
        if args.offline:
            ok, missing, mismatched = _verify_offline(entries)
        else:
            client = boto3.client("s3", region_name=args.region) if args.region else boto3.client("s3")
            for entry in entries:
                key = entry.get("s3_key")
                if not key:
                    mismatched.append("missing s3_key")
                    continue
                head = _head_object(client, args.bucket, key)
                if head is None:
                    missing.append(key)
                    continue
                expected_bytes = entry.get("bytes")
                if isinstance(expected_bytes, int):
                    actual_bytes = head.get("ContentLength")
                    if actual_bytes is not None and actual_bytes != expected_bytes:
                        mismatched.append(key)
            ok = len(missing) == 0 and len(mismatched) == 0
        payload = {
            "ok": ok,
            "missing": missing,
            "mismatched": mismatched,
            "checked": entries,
            "elapsed_ms": int((time.time() - start) * 1000),
        }
        if args.json:
            print(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False))
        else:
            if ok:
                print("OK: verification passed")
            else:
                if missing:
                    print("MISSING:")
                    for key in missing:
                        print(key)
                if mismatched:
                    print("MISMATCHED:")
                    for key in mismatched:
                        print(key)
        return 0 if ok else 2
    except SystemExit as exc:
        if args.json:
            payload = {
                "ok": False,
                "missing": [],
                "mismatched": [],
                "checked": [],
                "elapsed_ms": int((time.time() - start) * 1000),
            }
            print(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False))
        return 2 if exc.code in (None, 2) else 1
    except Exception:
        if args.json:
            payload = {
                "ok": False,
                "missing": [],
                "mismatched": [],
                "checked": [],
                "elapsed_ms": int((time.time() - start) * 1000),
            }
            print(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False))
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
