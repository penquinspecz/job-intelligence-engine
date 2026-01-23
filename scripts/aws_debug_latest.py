#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Optional

import boto3


@dataclass
class RunObject:
    run_id: str
    last_modified: Optional[datetime]


def _runs_prefix(prefix: str) -> str:
    clean = prefix.strip("/")
    return f"{clean}/runs/" if clean else "runs/"


def _parse_run_id(run_id: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(run_id.replace("Z", "+00:00"))
    except Exception:
        return None


def _select_latest_run_id(objs: Iterable[RunObject]) -> Optional[str]:
    best = None
    for obj in objs:
        ts = _parse_run_id(obj.run_id)
        if ts is None:
            ts = obj.last_modified
        if ts is None:
            continue
        if best is None or ts > best[0]:
            best = (ts, obj.run_id)
    return best[1] if best else None


def _list_run_ids(s3, bucket: str, prefix: str) -> list[RunObject]:
    runs_prefix = _runs_prefix(prefix)
    token = None
    run_ids: dict[str, RunObject] = {}
    while True:
        kwargs = {"Bucket": bucket, "Prefix": runs_prefix}
        if token:
            kwargs["ContinuationToken"] = token
        resp = s3.list_objects_v2(**kwargs)
        for obj in resp.get("Contents") or []:
            key = obj.get("Key") or ""
            if runs_prefix not in key:
                continue
            rest = key.split(runs_prefix, 1)[1]
            run_id = rest.split("/", 1)[0]
            if not run_id:
                continue
            run_ids.setdefault(run_id, RunObject(run_id=run_id, last_modified=obj.get("LastModified")))
        if not resp.get("IsTruncated"):
            break
        token = resp.get("NextContinuationToken")
    return list(run_ids.values())


def _get_json(s3, bucket: str, key: str) -> Optional[dict]:
    try:
        resp = s3.get_object(Bucket=bucket, Key=key)
    except Exception:
        return None
    body = resp.get("Body")
    if body is None:
        return None
    data = json.loads(body.read().decode("utf-8"))
    return data if isinstance(data, dict) else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bucket", default=os.environ.get("BUCKET", ""))
    ap.add_argument("--prefix", default=os.environ.get("PREFIX", "jobintel"))
    ap.add_argument("--provider", default=os.environ.get("PROVIDER", ""))
    ap.add_argument("--profile", default=os.environ.get("PROFILE", ""))
    ap.add_argument("--region", default=os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION"))
    args = ap.parse_args()

    if not args.bucket:
        raise SystemExit("Missing bucket (set BUCKET or --bucket)")

    s3 = boto3.client("s3", region_name=args.region)
    run_ids = _list_run_ids(s3, args.bucket, args.prefix)
    latest = _select_latest_run_id(run_ids)
    if not latest:
        print("No runs found.")
        return 0

    run_key = f"{args.prefix.strip('/')}/runs/{latest}/run_report.json".strip("/")
    run_report = _get_json(s3, args.bucket, run_key)
    print(f"Latest run_id: {latest}")
    print(f"run_report.json: s3://{args.bucket}/{run_key}")
    print(json.dumps(run_report or {}, indent=2, sort_keys=True))

    state_key = f"{args.prefix.strip('/')}/state/last_success.json".strip("/")
    state = _get_json(s3, args.bucket, state_key)
    print(f"last_success.json: s3://{args.bucket}/{state_key}")
    print(json.dumps(state or {}, indent=2, sort_keys=True))

    if args.provider and args.profile:
        pp_key = f"{args.prefix.strip('/')}/state/{args.provider}/{args.profile}/last_success.json".strip("/")
        pp_state = _get_json(s3, args.bucket, pp_key)
        print(f"provider last_success.json: s3://{args.bucket}/{pp_key}")
        print(json.dumps(pp_state or {}, indent=2, sort_keys=True))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
