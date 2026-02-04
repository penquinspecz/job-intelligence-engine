#!/usr/bin/env python3
from __future__ import annotations

import argparse
import getpass
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

ERROR_BANNED = "unrecognized arguments: python scripts/run_daily.py"


def find_repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in [here.parent, *here.parents]:
        if (parent / ".git").exists():
            return parent
    return here.parent.parent


def _require_tool(name: str) -> None:
    if shutil.which(name) is None:
        raise SystemExit(f"Missing required tool: {name}")


def _run(cmd: list[str], *, cwd: Optional[Path] = None) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            check=True,
            text=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as exc:
        print(f"Command failed: {' '.join(cmd)}")
        if exc.stdout:
            print(exc.stdout)
        if exc.stderr:
            print(exc.stderr, file=sys.stderr)
        raise


def _prompt(label: str, default: Optional[str] = None) -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{label}{suffix}: ").strip()
    return value or (default or "")


def _prompt_secret(label: str) -> str:
    try:
        value = getpass.getpass(f"{label} (hidden): ").strip()
    except Exception:
        print("Warning: unable to hide input; value will be visible.")
        value = input(f"{label}: ").strip()
    if not value:
        raise SystemExit(f"{label} is required.")
    return value


def parse_csv_list(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def write_tfvars(path: Path, data: dict[str, object]) -> None:
    lines: list[str] = []
    for key, value in data.items():
        if isinstance(value, list):
            quoted = ",".join(f'"{item}"' for item in value)
            lines.append(f"{key} = [{quoted}]")
        else:
            lines.append(f'{key} = "{value}"')
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _choose_tf(tool_hint: Optional[str] = None) -> str:
    if tool_hint:
        return tool_hint
    return "tofu" if shutil.which("tofu") else "terraform"


def _ssm_put_parameter(region: str, name: str, value: str) -> None:
    cmd = [
        "aws",
        "ssm",
        "put-parameter",
        "--region",
        region,
        "--name",
        name,
        "--type",
        "SecureString",
        "--value",
        value,
        "--overwrite",
    ]
    _run(cmd)


def _run_task(region: str, cluster_arn: str, taskdef: str, subnets: list[str], secgroups: list[str]) -> None:
    net = f"awsvpcConfiguration={{subnets=[{','.join(subnets)}],securityGroups=[{','.join(secgroups)}],assignPublicIp=ENABLED}}"
    cmd = [
        "aws",
        "ecs",
        "run-task",
        "--region",
        region,
        "--cluster",
        cluster_arn,
        "--task-definition",
        taskdef,
        "--launch-type",
        "FARGATE",
        "--network-configuration",
        net,
    ]
    _run(cmd)


def _normalize_list(value: str) -> list[str]:
    return parse_csv_list(value)


__all__ = ["parse_csv_list", "write_tfvars"]


def _latest_log_stream(region: str, log_group: str) -> Optional[str]:
    cmd = [
        "aws",
        "logs",
        "describe-log-streams",
        "--region",
        region,
        "--log-group-name",
        log_group,
        "--order-by",
        "LastEventTime",
        "--descending",
        "--max-items",
        "1",
    ]
    result = _run(cmd)
    payload = json.loads(result.stdout or "{}")
    streams = payload.get("logStreams") or []
    if not streams:
        return None
    return streams[0].get("logStreamName")


def _fetch_logs(region: str, log_group: str, log_stream: str) -> str:
    cmd = [
        "aws",
        "logs",
        "get-log-events",
        "--region",
        region,
        "--log-group-name",
        log_group,
        "--log-stream-name",
        log_stream,
        "--limit",
        "1000",
    ]
    result = _run(cmd)
    payload = json.loads(result.stdout or "{}")
    events = payload.get("events") or []
    return "\n".join(event.get("message", "") for event in events)


def _tail_logs_for_error(region: str, log_group: str, seconds: int = 60) -> bool:
    try:
        stream = _latest_log_stream(region, log_group)
    except Exception:
        print("Warning: unable to list log streams.")
        return False
    if not stream:
        print("Warning: no log streams found.")
        return False
    end = time.time() + seconds
    while time.time() < end:
        try:
            text = _fetch_logs(region, log_group, stream)
        except Exception:
            print("Warning: unable to fetch log events.")
            return False
        if ERROR_BANNED in text:
            return True
        time.sleep(5)
    return False


def _read_image_uri() -> str:
    value = os.environ.get("IMAGE_URI", "").strip()
    if not value:
        raise SystemExit("IMAGE_URI env var must be set (ECR image URI).")
    return value


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--region", default="")
    ap.add_argument("--tf-tool", default="")
    args = ap.parse_args()

    _require_tool("aws")
    _require_tool("docker")
    _run(["aws", "sts", "get-caller-identity"])

    region = args.region or _prompt("AWS region", "us-east-1")
    cluster_arn = _prompt("ECS_CLUSTER_ARN")
    s3_bucket = _prompt("S3_BUCKET")
    subnet_ids = parse_csv_list(_prompt("SUBNET_IDS (comma-separated)"))
    security_group_ids = parse_csv_list(_prompt("SECURITY_GROUP_IDS (comma-separated)"))
    openai_ssm = _prompt("SSM param for OPENAI_API_KEY", "/jobintel/prod/openai_api_key")
    discord_ssm = _prompt("SSM param for DISCORD_WEBHOOK_URL", "/jobintel/prod/discord_webhook_url")

    openai_value = _prompt_secret("OPENAI_API_KEY")
    discord_value = _prompt_secret("DISCORD_WEBHOOK_URL")

    _ssm_put_parameter(region, openai_ssm, openai_value)
    _ssm_put_parameter(region, discord_ssm, discord_value)

    repo_root = find_repo_root()
    infra_dir = repo_root / "ops" / "aws" / "infra"
    tfvars_path = infra_dir / "terraform.tfvars"
    image_uri = _read_image_uri()

    tfvars_payload = {
        "container_image": image_uri,
        "ecs_cluster_arn": cluster_arn,
        "s3_bucket": s3_bucket,
        "subnet_ids": subnet_ids,
        "security_group_ids": security_group_ids,
        "openai_api_key_ssm_param": openai_ssm,
        "discord_webhook_url_ssm_param": discord_ssm,
    }
    write_tfvars(tfvars_path, tfvars_payload)

    tf_tool = _choose_tf(args.tf_tool or None)
    _run([tf_tool, "init"], cwd=infra_dir)
    _run([tf_tool, "apply", "-auto-approve"], cwd=infra_dir)

    _run([sys.executable, str(repo_root / "scripts" / "aws_oneoff_run.py")])
    taskdef = "jobintel-daily"
    _run_task(region, cluster_arn, taskdef, subnet_ids, security_group_ids)

    has_error = _tail_logs_for_error(region, "/ecs/jobintel", seconds=60)
    if has_error:
        print(f"Detected error in logs: {ERROR_BANNED}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
