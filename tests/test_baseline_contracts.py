from __future__ import annotations

import importlib
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
import scripts.run_daily as run_daily_module
from ji_engine.utils.verification import compute_sha256_file

pytestmark = pytest.mark.skipif(boto3 is None or mock_s3 is None, reason="boto3/moto not installed")


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _setup_run_dir(tmp_path: Path, run_id: str, provider: str = "openai", profile: str = "cs") -> Path:
    run_dir = tmp_path / "state" / "runs" / publish_s3._sanitize_run_id(run_id)
    provider_dir = run_dir / provider / profile
    provider_dir.mkdir(parents=True, exist_ok=True)
    ranked = provider_dir / f"{provider}_ranked_jobs.{profile}.json"
    ranked.write_text(
        json.dumps(
            [
                {"job_id": "1", "title": "A", "apply_url": "x", "score": 10},
                {"job_id": "2", "title": "B", "apply_url": "y", "score": 9},
            ]
        ),
        encoding="utf-8",
    )
    verifiable = {
        f"{provider}:{profile}:ranked_json": {
            "path": f"{provider}_ranked_jobs.{profile}.json",
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
            "providers": [provider],
            "profiles": [profile],
            "timestamps": {"ended_at": run_id},
            "verifiable_artifacts": verifiable,
        },
    )
    return run_dir


def _load_ranked(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_contract_first_run_writes_pointer_and_new_equals_total(tmp_path, monkeypatch):
    with mock_s3():
        bucket = "bucket"
        prefix = "jobintel"
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket=bucket)
        monkeypatch.setattr(publish_s3, "RUN_METADATA_DIR", tmp_path / "state" / "runs")

        run_id = "2026-01-01T00:00:00Z"
        _setup_run_dir(tmp_path, run_id)

        publish_s3.publish_run(
            run_id=run_id,
            bucket=bucket,
            prefix=prefix,
            dry_run=False,
            require_s3=True,
            write_last_success=True,
        )

        # pointer exists
        ptr = client.get_object(Bucket=bucket, Key=f"{prefix}/state/last_success.json")
        assert ptr["Body"].read()

        # first-run diff: no baseline => new == total
        run_daily = importlib.reload(run_daily_module)
        curr = _load_ranked(
            tmp_path
            / "state"
            / "runs"
            / publish_s3._sanitize_run_id(run_id)
            / "openai"
            / "cs"
            / "openai_ranked_jobs.cs.json"
        )
        new, changed, removed, _ = run_daily._diff([], curr)
        assert len(new) == len(curr)
        assert len(changed) == 0
        assert len(removed) == 0


def test_contract_second_run_reuses_pointer_and_new_zero(tmp_path, monkeypatch):
    with mock_s3():
        bucket = "bucket"
        prefix = "jobintel"
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket=bucket)
        monkeypatch.setattr(publish_s3, "RUN_METADATA_DIR", tmp_path / "state" / "runs")

        run_id = "2026-01-01T00:00:00Z"
        _setup_run_dir(tmp_path, run_id)
        publish_s3.publish_run(
            run_id=run_id,
            bucket=bucket,
            prefix=prefix,
            dry_run=False,
            require_s3=True,
            write_last_success=True,
        )

        run_daily = importlib.reload(run_daily_module)
        baseline = run_daily._resolve_s3_baseline(
            "openai",
            "cs",
            "2026-01-02T00:00:00Z",
            bucket=bucket,
            prefix=prefix,
        )
        assert baseline.run_id == run_id
        assert baseline.ranked_path is not None
        prev = _load_ranked(baseline.ranked_path)
        curr = _load_ranked(
            tmp_path
            / "state"
            / "runs"
            / publish_s3._sanitize_run_id(run_id)
            / "openai"
            / "cs"
            / "openai_ranked_jobs.cs.json"
        )
        new, changed, removed, _ = run_daily._diff(prev, curr)
        assert len(new) == 0
        assert len(changed) == 0
        assert len(removed) == 0


def test_contract_failed_run_does_not_update_pointer(tmp_path, monkeypatch):
    with mock_s3():
        bucket = "bucket"
        prefix = "jobintel"
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket=bucket)
        monkeypatch.setattr(publish_s3, "RUN_METADATA_DIR", tmp_path / "state" / "runs")

        run_id = "2026-01-01T00:00:00Z"
        _setup_run_dir(tmp_path, run_id)
        publish_s3.publish_run(
            run_id=run_id,
            bucket=bucket,
            prefix=prefix,
            dry_run=False,
            require_s3=True,
            write_last_success=False,
        )

        with pytest.raises(client.exceptions.NoSuchKey):
            client.get_object(Bucket=bucket, Key=f"{prefix}/state/last_success.json")


def test_contract_deleted_pointer_returns_first_run_behavior(tmp_path, monkeypatch):
    with mock_s3():
        bucket = "bucket"
        prefix = "jobintel"
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket=bucket)
        monkeypatch.setattr(publish_s3, "RUN_METADATA_DIR", tmp_path / "state" / "runs")

        run_id = "2026-01-01T00:00:00Z"
        _setup_run_dir(tmp_path, run_id)
        publish_s3.publish_run(
            run_id=run_id,
            bucket=bucket,
            prefix=prefix,
            dry_run=False,
            require_s3=True,
            write_last_success=True,
        )

        # delete pointer and remove run_report to disable fallback
        client.delete_object(Bucket=bucket, Key=f"{prefix}/state/last_success.json")
        client.delete_object(Bucket=bucket, Key=f"{prefix}/runs/{run_id}/run_report.json")

        run_daily = importlib.reload(run_daily_module)
        baseline = run_daily._resolve_s3_baseline(
            "openai",
            "cs",
            "2026-01-02T00:00:00Z",
            bucket=bucket,
            prefix=prefix,
        )
        assert baseline.run_id is None
        curr = _load_ranked(
            tmp_path
            / "state"
            / "runs"
            / publish_s3._sanitize_run_id(run_id)
            / "openai"
            / "cs"
            / "openai_ranked_jobs.cs.json"
        )
        new, changed, removed, _ = run_daily._diff([], curr)
        assert len(new) == len(curr)
        assert len(changed) == 0
        assert len(removed) == 0
