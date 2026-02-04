#!/usr/bin/env python3
from __future__ import annotations

import argparse
import logging
import os
import re
from pathlib import Path
from typing import Any

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

_ASSIGN_RE = re.compile(r"^([A-Za-z0-9_]+)\s*=\s*(.+)$")
_QUOTED_RE = re.compile(r"\"([^\"]+)\"")


def parse_tfvars(text: str) -> dict[str, Any]:
    data: dict[str, Any] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("//"):
            continue
        match = _ASSIGN_RE.match(line)
        if not match:
            continue
        key, value = match.group(1), match.group(2).strip()
        if value.startswith("["):
            data[key] = _QUOTED_RE.findall(value)
        elif value.startswith('"') and value.endswith('"'):
            data[key] = value.strip('"')
        else:
            data[key] = value
    return data


def build_run_task_command(config: dict[str, Any]) -> str:
    cluster = config.get("ecs_cluster_arn", "<cluster-arn>")
    taskdef = config.get("task_definition_arn", "jobintel-daily")
    subnets = config.get("subnet_ids", ["subnet-xxx"])
    secgroups = config.get("security_group_ids", ["sg-xxx"])
    region = config.get("aws_region") or os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION", "")
    subnet_part = ",".join(subnets) if isinstance(subnets, list) else str(subnets)
    sg_part = ",".join(secgroups) if isinstance(secgroups, list) else str(secgroups)
    region_flag = f" --region {region}" if region else ""
    return (
        "aws ecs run-task"
        f"{region_flag} \\"
        f"\n  --cluster {cluster} \\"
        f"\n  --task-definition {taskdef} \\"
        "\n  --launch-type FARGATE \\"
        "\n  --network-configuration "
        f'"awsvpcConfiguration={{subnets=[{subnet_part}],securityGroups=[{sg_part}],assignPublicIp=ENABLED}}"'
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--tfvars",
        default=os.environ.get("JOBINTEL_TFVARS_PATH", "ops/aws/infra/terraform.tfvars"),
        help="Path to terraform.tfvars",
    )
    args = ap.parse_args()
    tfvars_path = Path(args.tfvars)
    if not tfvars_path.exists():
        logger.error("tfvars not found: %s", tfvars_path)
        return 2
    config = parse_tfvars(tfvars_path.read_text(encoding="utf-8"))
    logger.info("One-off ECS task (edit if needed):")
    logger.info(build_run_task_command(config))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
