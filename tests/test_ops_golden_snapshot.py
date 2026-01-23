from __future__ import annotations

import json
from pathlib import Path

import pytest

try:
    import boto3
    from moto import mock_s3
except Exception:  # pragma: no cover
    boto3 = None
    mock_s3 = None

import scripts.publish_s3 as publish_s3

pytestmark = pytest.mark.skipif(boto3 is None or mock_s3 is None, reason="boto3/moto not installed")


REQUIRED_TOP_KEYS = {
    "run_id",
    "run_report_schema_version",
    "selection",
    "provenance",
    "provenance_by_provider",
    "diff_counts",
    "success",
    "started_at",
    "ended_at",
}


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _setup_run_dir(tmp_path: Path, run_id: str) -> Path:
    run_dir = tmp_path / "state" / "runs" / publish_s3._sanitize_run_id(run_id)
    provider_dir = run_dir / "openai" / "cs"
    provider_dir.mkdir(parents=True, exist_ok=True)
    (provider_dir / "openai_ranked_jobs.cs.json").write_text("[]", encoding="utf-8")
    _write_json(
        run_dir / "index.json",
        {
            "run_id": run_id,
            "timestamp": run_id,
            "providers": {"openai": {"profiles": {"cs": {"diff_counts": {"new": 0}}}}},
        },
    )
    _write_json(
        run_dir / "run_report.json",
        {
            "run_id": run_id,
            "run_report_schema_version": 1,
            "selection": {"scrape_provenance": {"openai": {"scrape_mode": "snapshot"}}},
            "provenance": {"openai": {"scrape_mode": "snapshot"}},
            "provenance_by_provider": {"openai": {"scrape_mode": "snapshot"}},
            "diff_counts": {"cs": {"new": 0, "changed": 0, "removed": 0}},
            "success": True,
            "started_at": "2026-01-01T00:00:00Z",
            "ended_at": "2026-01-01T00:00:05Z",
        },
    )
    return run_dir


def test_ops_golden_snapshot_contract(tmp_path):
    with mock_s3():
        bucket = "bucket"
        prefix = "jobintel"
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket=bucket)

        run_id = "2026-01-01T00:00:00Z"
        run_dir = _setup_run_dir(tmp_path, run_id)
        report = json.loads((run_dir / "run_report.json").read_text(encoding="utf-8"))

        missing = REQUIRED_TOP_KEYS - set(report.keys())
        assert not missing, f"Missing required run_report keys: {sorted(missing)}"
        assert report["run_report_schema_version"] == 1
        assert "openai" in report["provenance_by_provider"]

        publish_s3.publish_run(
            run_id=run_id,
            bucket=bucket,
            prefix=prefix,
            dry_run=False,
            require_s3=True,
            write_last_success=True,
        )

        global_ptr = client.get_object(Bucket=bucket, Key=f"{prefix}/state/last_success.json")
        assert global_ptr["Body"].read()
