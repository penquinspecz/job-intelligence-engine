from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional

RUN_ID_REGEX = re.compile(r"JOBINTEL_RUN_ID=([^\s]+)")
PROVENANCE_REGEX = re.compile(r"\[run_scrape\]\[provenance\]\s+(\{.*\})")
S3_STATUS_REGEX = re.compile(r"s3_status=([a-z_]+)")
PUBLISH_POINTER_REGEX = re.compile(r"PUBLISH_CONTRACT .*pointer_global=([a-z_]+)")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def extract_run_id(log_text: str) -> Optional[str]:
    match = RUN_ID_REGEX.search(log_text)
    if not match:
        return None
    return match.group(1)


def extract_provenance_line(log_text: str) -> Optional[str]:
    matches = PROVENANCE_REGEX.findall(log_text)
    if not matches:
        return None
    return matches[-1]


def extract_provenance_payload(log_text: str) -> Optional[Dict[str, Any]]:
    line = extract_provenance_line(log_text)
    if not line:
        return None
    try:
        payload = json.loads(line)
    except json.JSONDecodeError:
        return None
    if isinstance(payload, dict):
        return payload
    return None


def extract_publish_markers(log_text: str) -> Dict[str, Optional[str]]:
    s3_match = S3_STATUS_REGEX.search(log_text)
    pointer_match = PUBLISH_POINTER_REGEX.search(log_text)
    return {
        "s3_status": s3_match.group(1) if s3_match else None,
        "pointer_global": pointer_match.group(1) if pointer_match else None,
    }


def required_provenance_issues(provenance: Dict[str, Any]) -> list[str]:
    issues: list[str] = []
    if provenance.get("live_attempted") is not True:
        issues.append("provenance.live_attempted must be true")
    if provenance.get("live_result") != "success":
        issues.append("provenance.live_result must be success")
    if str(provenance.get("scrape_mode", "")).lower() != "live":
        issues.append("provenance.scrape_mode must be live")
    if provenance.get("snapshot_used") is not False:
        issues.append("provenance.snapshot_used must be false")
    if provenance.get("parsed_job_count") is None:
        issues.append("provenance.parsed_job_count is required")
    if "policy_snapshot" not in provenance:
        issues.append("provenance.policy_snapshot is required")
    if provenance.get("robots_final_allowed") is None:
        issues.append("provenance.robots_final_allowed is required")
    return issues


def build_liveproof_capture(
    *,
    run_id: str,
    cluster_name: str,
    namespace: str,
    job_name: str,
    pod_name: str,
    image: str,
    bucket: str,
    prefix: str,
    verify_exit_code: int,
    verify_log_path: str,
    liveproof_log_path: str,
    provenance: Dict[str, Any],
    publish_markers: Dict[str, Optional[str]],
) -> Dict[str, Any]:
    return {
        "capture_schema_version": 1,
        "captured_at": utc_now_iso(),
        "cluster_name": cluster_name,
        "namespace": namespace,
        "job_name": job_name,
        "pod_name": pod_name,
        "image": image,
        "run_id": run_id,
        "bucket": bucket,
        "prefix": prefix,
        "verify_exit_code": verify_exit_code,
        "verify_log_path": verify_log_path,
        "liveproof_log_path": liveproof_log_path,
        "publish_markers": publish_markers,
        "provenance": {
            "live_attempted": provenance.get("live_attempted"),
            "live_result": provenance.get("live_result"),
            "scrape_mode": provenance.get("scrape_mode"),
            "snapshot_used": provenance.get("snapshot_used"),
            "parsed_job_count": provenance.get("parsed_job_count"),
            "policy_snapshot": provenance.get("policy_snapshot"),
            "robots_final_allowed": provenance.get("robots_final_allowed"),
            "rate_limit_min_delay_s": provenance.get("rate_limit_min_delay_s"),
            "backoff_base_s": provenance.get("backoff_base_s"),
            "circuit_breaker_threshold": provenance.get("circuit_breaker_threshold"),
        },
    }
