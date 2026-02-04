import importlib
import json
from pathlib import Path

import pytest

import ji_engine.config as config

try:
    import boto3
    from moto import mock_s3
except Exception:  # pragma: no cover
    boto3 = None
    mock_s3 = None

import scripts.publish_s3 as publish_s3
import scripts.run_daily as run_daily_module
from ji_engine.utils.verification import compute_sha256_file

pytestmark = pytest.mark.skipif(boto3 is None or mock_s3 is None, reason="boto3/moto not installed")


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _setup_run_dir(tmp_path: Path, run_id: str) -> Path:
    run_dir = tmp_path / "state" / "runs" / publish_s3._sanitize_run_id(run_id)
    provider_dir = run_dir / "openai" / "cs"
    provider_dir.mkdir(parents=True, exist_ok=True)
    ranked = provider_dir / "openai_ranked_jobs.cs.json"
    ranked.write_text(
        json.dumps([{"job_id": "1", "title": "A", "apply_url": "x"}]),
        encoding="utf-8",
    )
    verifiable = {
        "openai:cs:ranked_json": {
            "path": "openai_ranked_jobs.cs.json",
            "sha256": compute_sha256_file(ranked),
            "bytes": ranked.stat().st_size,
            "hash_algo": "sha256",
        }
    }
    _write_json(
        run_dir / "run_report.json",
        {
            "run_id": run_id,
            "run_report_schema_version": 1,
            "providers": ["openai"],
            "profiles": ["cs"],
            "timestamps": {"ended_at": run_id},
            "verifiable_artifacts": verifiable,
        },
    )
    return run_dir


def test_pointers_written_and_read(monkeypatch, tmp_path, caplog):
    with mock_s3():
        bucket = "bucket"
        prefix = "jobintel"
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket=bucket)

        monkeypatch.setattr(publish_s3, "RUN_METADATA_DIR", tmp_path / "state" / "runs")

        run_daily = importlib.reload(run_daily_module)

        with caplog.at_level("INFO"):
            run_daily._resolve_s3_baseline(  # pylint: disable=protected-access
                "openai",
                "cs",
                "2026-01-02T00:00:00Z",
                bucket=bucket,
                prefix=prefix,
            )
        assert "status=not_found" in caplog.text

        run_id = "2026-01-01T00:00:00Z"
        _setup_run_dir(tmp_path, run_id)

        with caplog.at_level("INFO"):
            publish_s3.publish_run(
                run_id=run_id,
                bucket=bucket,
                prefix=prefix,
                dry_run=False,
                require_s3=True,
                write_last_success=True,
            )
        assert "writing baseline pointer" in caplog.text

        data_dir = tmp_path / "data"
        state_dir = tmp_path / "state"
        monkeypatch.setenv("JOBINTEL_DATA_DIR", str(data_dir))
        monkeypatch.setenv("JOBINTEL_STATE_DIR", str(state_dir))
        monkeypatch.setenv("S3_PUBLISH_ENABLED", "1")
        monkeypatch.setenv("JOBINTEL_S3_BUCKET", bucket)
        monkeypatch.setenv("JOBINTEL_S3_PREFIX", prefix)
        importlib.reload(config)
        current_ranked = data_dir / "openai_ranked_jobs.cs.json"
        current_ranked.parent.mkdir(parents=True, exist_ok=True)
        payload = [{"job_id": "1", "title": "A", "apply_url": "x"}]
        current_ranked.write_text(json.dumps(payload), encoding="utf-8")
        labeled = data_dir / "openai_labeled_jobs.json"
        labeled.write_text(json.dumps(payload), encoding="utf-8")

        with caplog.at_level("INFO"):
            summary = run_daily._build_delta_summary("2026-01-02T00:00:00Z", ["openai"], ["cs"])

        entry = summary["provider_profile"]["openai"]["cs"]
        assert entry["baseline_run_id"] == run_id
        assert entry["new_job_count"] == 0
        assert "Baseline pointer read" in caplog.text
