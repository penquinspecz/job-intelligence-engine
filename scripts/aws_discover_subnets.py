#!/usr/bin/env python3
from __future__ import annotations

try:
    import _bootstrap  # type: ignore
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

import argparse
import json
import os
import subprocess
import sys
from typing import Any, Dict, List, Optional, Set


def _run_aws(args: List[str]) -> Dict[str, Any]:
    result = subprocess.run(
        ["aws", *args],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "aws cli failed")
    return json.loads(result.stdout)


def _region() -> str:
    for key in ("JOBINTEL_AWS_REGION", "AWS_REGION", "AWS_DEFAULT_REGION"):
        value = os.getenv(key)
        if value:
            return value
    result = subprocess.run(
        ["aws", "configure", "get", "region"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip()
    raise RuntimeError("AWS region not set (set AWS_REGION/AWS_DEFAULT_REGION/JOBINTEL_AWS_REGION)")


def _tag_lookup(tags: Optional[List[Dict[str, str]]]) -> Dict[str, str]:
    if not tags:
        return {}
    return {tag.get("Key", ""): tag.get("Value", "") for tag in tags if tag.get("Key")}


def _summarize_tags(tags: Dict[str, str]) -> str:
    if not tags:
        return "<none>"
    parts = [f"{key}={tags[key]}" for key in sorted(tags.keys())]
    return ", ".join(parts)


def _preferred_vpcs(vpcs: List[Dict[str, Any]]) -> List[str]:
    jobintel = [vpc["VpcId"] for vpc in vpcs if "jobintel" in vpc.get("Name", "").lower()]
    if jobintel:
        return sorted(jobintel)
    defaults = [vpc["VpcId"] for vpc in vpcs if vpc.get("IsDefault")]
    if defaults:
        return sorted(defaults)
    return sorted(vpc["VpcId"] for vpc in vpcs)


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Discover AWS subnets for EKS bootstrap.")
    parser.add_argument(
        "--exclude-az",
        action="append",
        default=[],
        help="Availability Zone to exclude (repeatable).",
    )
    return parser.parse_args(argv)


def _normalize_excluded(values: List[str]) -> List[str]:
    seen: Set[str] = set()
    ordered: List[str] = []
    for value in values:
        if not value:
            continue
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def main(argv: Optional[List[str]] = None) -> int:
    try:
        args = _parse_args(argv)
        excluded_azs = _normalize_excluded(args.exclude_az)
        region = _region()
        vpcs_raw = _run_aws(["ec2", "describe-vpcs", "--region", region, "--output", "json"])
        subnets_raw = _run_aws(["ec2", "describe-subnets", "--region", region, "--output", "json"])
        vpcs: List[Dict[str, Any]] = []
        for vpc in vpcs_raw.get("Vpcs", []):
            tags = _tag_lookup(vpc.get("Tags"))
            vpcs.append(
                {
                    "VpcId": vpc.get("VpcId"),
                    "CidrBlock": vpc.get("CidrBlock"),
                    "IsDefault": bool(vpc.get("IsDefault")),
                    "Name": tags.get("Name", ""),
                }
            )
        vpcs = sorted(vpcs, key=lambda item: item["VpcId"])

        preferred_vpc_ids = _preferred_vpcs(vpcs)
        subnet_rows: List[Dict[str, Any]] = []
        for subnet in subnets_raw.get("Subnets", []):
            tags = _tag_lookup(subnet.get("Tags"))
            subnet_rows.append(
                {
                    "SubnetId": subnet.get("SubnetId"),
                    "VpcId": subnet.get("VpcId"),
                    "AvailabilityZone": subnet.get("AvailabilityZone"),
                    "CidrBlock": subnet.get("CidrBlock"),
                    "MapPublicIpOnLaunch": bool(subnet.get("MapPublicIpOnLaunch")),
                    "Tags": tags,
                    "TagsSummary": _summarize_tags(tags),
                }
            )

        def _sort_key(item: Dict[str, Any]) -> tuple:
            return (
                item.get("VpcId", ""),
                item.get("AvailabilityZone", ""),
                item.get("SubnetId", ""),
            )

        subnet_rows = sorted(subnet_rows, key=_sort_key)
        if excluded_azs:
            subnet_rows = [row for row in subnet_rows if row.get("AvailabilityZone") not in excluded_azs]
        selected = [row for row in subnet_rows if row.get("VpcId") in preferred_vpc_ids]
        if not selected:
            selected = subnet_rows

        selected_ids = [row["SubnetId"] for row in selected if row.get("SubnetId")]
        terraform_snippet = (
            "terraform apply -var 'subnet_ids=["
            + ",".join(f'"{sid}"' for sid in selected_ids)
            + "]' -var 's3_bucket=<bucket>'"
        )

        print("AWS subnet discovery")
        print(f"Region: {region}")
        print(f"Preferred VPCs: {', '.join(preferred_vpc_ids) if preferred_vpc_ids else '<none>'}")
        if excluded_azs:
            print(f"Excluded AZs: {', '.join(excluded_azs)}")
        print("")
        print("VPCs:")
        for vpc in vpcs:
            print(
                f"- {vpc['VpcId']} cidr={vpc['CidrBlock']} "
                f"default={str(vpc['IsDefault']).lower()} name={vpc['Name'] or '<none>'}"
            )
        print("")
        print("Subnets (selected first):")
        for row in selected:
            print(
                f"- {row['SubnetId']} vpc={row['VpcId']} az={row['AvailabilityZone']} "
                f"cidr={row['CidrBlock']} map_public_ip={str(row['MapPublicIpOnLaunch']).lower()} "
                f"tags={row['TagsSummary']}"
            )
        print("")
        print("Suggested terraform command:")
        print(terraform_snippet)
        print("")
        payload = {
            "region": region,
            "vpcs": vpcs,
            "preferred_vpc_ids": preferred_vpc_ids,
            "excluded_azs": excluded_azs,
            "selected_subnet_ids": selected_ids,
            "subnets": selected,
            "terraform_snippet": terraform_snippet,
        }
        print(json.dumps(payload, sort_keys=True))
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
