#!/usr/bin/env python3
from __future__ import annotations

import argparse
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import boto3

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def _parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--rule-name",
        default=os.environ.get("JOBINTEL_AWS_RULE_NAME", "jobintel-daily"),
        help="EventBridge rule name (default: jobintel-daily)",
    )
    ap.add_argument(
        "--region",
        default=os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION"),
        help="AWS region (default: AWS_REGION/AWS_DEFAULT_REGION)",
    )
    return ap.parse_args()


def _latest_invocation_time(datapoints: list[dict]) -> Optional[str]:
    if not datapoints:
        return None
    latest = max((d.get("Timestamp") for d in datapoints if d.get("Timestamp")), default=None)
    if not latest:
        return None
    if isinstance(latest, datetime):
        return latest.astimezone(timezone.utc).isoformat()
    return str(latest)


def _get_rule_state(events, rule_name: str) -> Optional[dict]:
    try:
        return events.describe_rule(Name=rule_name)
    except Exception as exc:
        logger.error("describe_rule failed: %r", exc)
        return None


def _get_targets(events, rule_name: str) -> list[dict]:
    try:
        resp = events.list_targets_by_rule(Rule=rule_name)
    except Exception as exc:
        logger.error("list_targets_by_rule failed: %r", exc)
        return []
    return resp.get("Targets") or []


def _get_invocation_time(cloudwatch, rule_name: str) -> Optional[str]:
    try:
        resp = cloudwatch.get_metric_statistics(
            Namespace="AWS/Events",
            MetricName="Invocations",
            Dimensions=[{"Name": "RuleName", "Value": rule_name}],
            StartTime=datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0) - timedelta(days=7),
            EndTime=datetime.now(timezone.utc),
            Period=3600,
            Statistics=["Sum"],
        )
    except Exception as exc:
        logger.info("CloudWatch invocation lookup failed: %r", exc)
        return None
    datapoints = resp.get("Datapoints") or []
    return _latest_invocation_time(datapoints)


def main() -> int:
    args = _parse_args()
    if not args.region:
        logger.warning("AWS region not set; set AWS_REGION or AWS_DEFAULT_REGION.")
    events = boto3.client("events", region_name=args.region)
    cloudwatch = boto3.client("cloudwatch", region_name=args.region)

    rule = _get_rule_state(events, args.rule_name)
    if not rule:
        return 2

    logger.info("Rule: %s", rule.get("Name"))
    logger.info("State: %s", rule.get("State"))
    logger.info("Schedule: %s", rule.get("ScheduleExpression"))
    if rule.get("LastModified"):
        logger.info("Last modified: %s", rule.get("LastModified"))

    targets = _get_targets(events, args.rule_name)
    if targets:
        target = targets[0]
        logger.info("Target ARN: %s", target.get("Arn"))
        ecs = target.get("EcsParameters") or {}
        if ecs:
            logger.info("Task definition: %s", ecs.get("TaskDefinitionArn"))
            logger.info("Cluster: %s", target.get("Arn"))
    else:
        logger.info("Targets: none")

    last_invoked = _get_invocation_time(cloudwatch, args.rule_name)
    if last_invoked:
        logger.info("Last invocation (CloudWatch): %s", last_invoked)
    else:
        logger.info("Last invocation (CloudWatch): unavailable")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
