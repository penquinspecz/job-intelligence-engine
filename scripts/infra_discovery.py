#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from typing import Any, Dict, List, Optional


def _get_boto3():
    try:
        import boto3  # type: ignore

        return boto3
    except Exception:
        return None


def _parse_arn_name(arn: str) -> str:
    if "/" in arn:
        return arn.rsplit("/", 1)[-1]
    return arn


def _account_and_region(session) -> tuple[Optional[str], Optional[str], List[str]]:
    errors: List[str] = []
    try:
        sts = session.client("sts")
        ident = sts.get_caller_identity()
        account_id = ident.get("Account")
    except Exception as exc:
        errors.append(f"sts_error:{exc.__class__.__name__}")
        account_id = None
    region = (
        session.region_name
        or os.getenv("AWS_REGION")
        or os.getenv("AWS_DEFAULT_REGION")
        or os.getenv("JOBINTEL_AWS_REGION")
    )
    return account_id, region, errors


def _discover_ecs(session) -> Dict[str, Any]:
    ecs = session.client("ecs")
    clusters: List[Dict[str, Any]] = []
    cluster_arns = ecs.list_clusters().get("clusterArns", [])
    for cluster_arn in sorted(cluster_arns):
        services: List[Dict[str, str]] = []
        paginator = ecs.get_paginator("list_services")
        for page in paginator.paginate(cluster=cluster_arn):
            for svc_arn in page.get("serviceArns", []):
                services.append({"arn": svc_arn, "name": _parse_arn_name(svc_arn)})
        services.sort(key=lambda item: item["name"])
        clusters.append(
            {
                "arn": cluster_arn,
                "name": _parse_arn_name(cluster_arn),
                "services": services,
            }
        )
    clusters.sort(key=lambda item: item["name"])
    return {"clusters": clusters}


def _discover_eks(session) -> Dict[str, Any]:
    eks = session.client("eks")
    clusters = eks.list_clusters().get("clusters", [])
    return {"clusters": sorted(clusters)}


def _discover_s3(session) -> Dict[str, Any]:
    s3 = session.client("s3")
    buckets = [b.get("Name") for b in s3.list_buckets().get("Buckets", []) if b.get("Name")]
    buckets = sorted(buckets)
    pattern = os.getenv("JOBINTEL_S3_BUCKET") or "jobintel"
    matching = [name for name in buckets if pattern in name]
    return {"buckets": buckets, "matching": matching, "pattern": pattern}


def _render_text(payload: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append(f"AWS Account: {payload.get('account_id')}")
    lines.append(f"Region: {payload.get('region')}")
    ecs = payload.get("ecs", {})
    ecs_clusters = ecs.get("clusters", []) if isinstance(ecs, dict) else []
    lines.append(f"ECS clusters: {len(ecs_clusters)}")
    for cluster in ecs_clusters:
        lines.append(f"  - {cluster.get('name')}")
        services = cluster.get("services", []) or []
        for svc in services:
            lines.append(f"    - {svc.get('name')}")
    eks = payload.get("eks", {})
    eks_clusters = eks.get("clusters", []) if isinstance(eks, dict) else []
    lines.append(f"EKS clusters: {len(eks_clusters)}")
    for name in eks_clusters:
        lines.append(f"  - {name}")
    s3 = payload.get("s3", {})
    matching = s3.get("matching", []) if isinstance(s3, dict) else []
    lines.append(f"S3 buckets (matching): {len(matching)}")
    for name in matching:
        lines.append(f"  - {name}")
    errors = payload.get("errors") or []
    if errors:
        lines.append("Errors:")
        for err in errors:
            lines.append(f"  - {err}")
    return "\n".join(lines)


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Discover AWS infra (read-only).")
    parser.add_argument("--json", action="store_true", help="Emit JSON only.")
    args = parser.parse_args(argv)

    boto3 = _get_boto3()
    payload: Dict[str, Any] = {
        "account_id": None,
        "region": None,
        "ecs": {"clusters": []},
        "eks": {"clusters": []},
        "s3": {"buckets": [], "matching": [], "pattern": os.getenv("JOBINTEL_S3_BUCKET") or "jobintel"},
        "errors": [],
    }
    if boto3 is None:
        payload["errors"].append("boto3_not_available")
    else:
        session = boto3.session.Session()
        account_id, region, errors = _account_and_region(session)
        payload["account_id"] = account_id
        payload["region"] = region
        payload["errors"].extend(errors)
        try:
            payload["ecs"] = _discover_ecs(session)
        except Exception as exc:
            payload["errors"].append(f"ecs_error:{exc.__class__.__name__}")
        try:
            payload["eks"] = _discover_eks(session)
        except Exception as exc:
            payload["errors"].append(f"eks_error:{exc.__class__.__name__}")
        try:
            payload["s3"] = _discover_s3(session)
        except Exception as exc:
            payload["errors"].append(f"s3_error:{exc.__class__.__name__}")

    payload["errors"] = sorted(set(payload["errors"]))

    if not args.json:
        print(_render_text(payload))
        print("---")
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
