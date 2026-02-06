from __future__ import annotations

from ji_engine.proof.liveproof import (
    build_liveproof_capture,
    extract_provenance_payload,
    extract_publish_markers,
    extract_run_id,
    required_provenance_issues,
)


def test_extract_receipt_markers_from_logs() -> None:
    logs = "\n".join(
        [
            "JOBINTEL_RUN_ID=2026-02-06T00:00:00Z",
            '[run_scrape][provenance] {"live_attempted": true, "live_result": "success", "scrape_mode": "live", "snapshot_used": false, "parsed_job_count": 10, "policy_snapshot": {"rate_limit_config": {}}, "robots_final_allowed": true}',
            "s3_status=ok",
            "PUBLISH_CONTRACT enabled=True required=True bucket=b prefix=p pointer_global=ok pointer_profiles={} error=None",
        ]
    )
    run_id = extract_run_id(logs)
    assert run_id == "2026-02-06T00:00:00Z"
    provenance = extract_provenance_payload(logs)
    assert provenance is not None
    assert provenance["live_result"] == "success"
    markers = extract_publish_markers(logs)
    assert markers == {"s3_status": "ok", "pointer_global": "ok"}


def test_required_provenance_issues_is_deterministic() -> None:
    valid = {
        "live_attempted": True,
        "live_result": "success",
        "scrape_mode": "live",
        "snapshot_used": False,
        "parsed_job_count": 1,
        "policy_snapshot": {"rate_limit_config": {"min_delay_s": 1.0}},
        "robots_final_allowed": True,
    }
    assert required_provenance_issues(valid) == []
    invalid = {"live_result": "skipped"}
    issues = required_provenance_issues(invalid)
    assert "provenance.live_result must be success" in issues
    assert "provenance.live_attempted must be true" in issues


def test_build_liveproof_capture_shape() -> None:
    payload = build_liveproof_capture(
        run_id="2026-02-06T00:00:00Z",
        cluster_name="jobintel-eks",
        namespace="jobintel",
        job_name="jobintel-liveproof-abc",
        pod_name="pod-123",
        image="repo/jobintel:tag",
        bucket="bucket-a",
        prefix="jobintel",
        verify_exit_code=0,
        verify_log_path="ops/proof/verify_published_s3-2026-02-06T00:00:00Z.log",
        liveproof_log_path="ops/proof/liveproof-2026-02-06T00:00:00Z.log",
        provenance={
            "live_attempted": True,
            "live_result": "success",
            "scrape_mode": "live",
            "snapshot_used": False,
            "parsed_job_count": 3,
            "policy_snapshot": {"rate_limit_config": {"min_delay_s": 1.0}},
            "robots_final_allowed": True,
            "rate_limit_min_delay_s": 1.0,
            "backoff_base_s": 1.0,
            "circuit_breaker_threshold": 3,
        },
        publish_markers={"s3_status": "ok", "pointer_global": "ok"},
    )
    assert payload["capture_schema_version"] == 1
    assert payload["run_id"] == "2026-02-06T00:00:00Z"
    assert payload["publish_markers"]["pointer_global"] == "ok"
    assert payload["provenance"]["live_result"] == "success"
