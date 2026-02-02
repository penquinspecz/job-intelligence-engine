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
from scripts import verify_published_s3
from ji_engine.utils.verification import compute_sha256_file

pytestmark = pytest.mark.skipif(boto3 is None or mock_s3 is None, reason="boto3/moto not installed")


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _setup_run_dir(tmp_path: Path, run_id: str) -> Path:
    run_dir = tmp_path / "state" / "runs" / publish_s3._sanitize_run_id(run_id)
    provider_dir = run_dir / "openai" / "cs"
    provider_dir.mkdir(parents=True, exist_ok=True)
    ranked_json = provider_dir / "openai_ranked_jobs.cs.json"
    ranked_json.write_text("[]", encoding="utf-8")
    ranked_families = provider_dir / "openai_ranked_families.cs.json"
    ranked_families.write_text("[]", encoding="utf-8")
    verifiable = {
        "openai:cs:ranked_json": {
            "path": "openai/cs/openai_ranked_jobs.cs.json",
            "sha256": compute_sha256_file(ranked_json),
            "hash_algo": "sha256",
        },
        "openai:cs:ranked_families_json": {
            "path": "openai/cs/openai_ranked_families.cs.json",
            "sha256": compute_sha256_file(ranked_families),
            "hash_algo": "sha256",
        },
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


def test_publish_s3_filters_providers_profiles(tmp_path: Path, monkeypatch) -> None:
    with mock_s3():
        bucket = "bucket"
        prefix = "jobintel"
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket=bucket)

        run_id = "2026-01-01T00:00:00Z"
        run_dir = _setup_run_dir(tmp_path, run_id)
        other_dir = run_dir / "openai" / "tam"
        other_dir.mkdir(parents=True, exist_ok=True)
        (other_dir / "openai_ranked_jobs.tam.json").write_text("[]", encoding="utf-8")
        monkeypatch.setattr(publish_s3, "RUN_METADATA_DIR", tmp_path / "state" / "runs")

        publish_s3.publish_run(
            run_id=run_id,
            bucket=bucket,
            prefix=prefix,
            run_dir=run_dir,
            dry_run=False,
            require_s3=True,
            providers=["openai"],
            profiles=["cs"],
            write_last_success=True,
        )

        keys = []
        paginator = client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket, Prefix=f"{prefix}/latest/openai/"):
            for item in page.get("Contents", []):
                keys.append(item["Key"])
        assert any(key.startswith(f"{prefix}/latest/openai/cs/") for key in keys)
        assert not any(key.startswith(f"{prefix}/latest/openai/tam/") for key in keys)


def test_publish_s3_uploads_expected_keys_and_content_types(tmp_path: Path, monkeypatch) -> None:
    with mock_s3():
        bucket = "bucket"
        prefix = "jobintel"
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket=bucket)

        run_id = "2026-01-01T00:00:00Z"
        run_dir = _setup_run_dir(tmp_path, run_id)
        monkeypatch.setattr(publish_s3, "RUN_METADATA_DIR", tmp_path / "state" / "runs")
        verify_published_s3.RUN_METADATA_DIR = tmp_path / "state" / "runs"

        publish_s3.publish_run(
            run_id=run_id,
            bucket=bucket,
            prefix=prefix,
            run_dir=run_dir,
            dry_run=False,
            require_s3=True,
            providers=["openai"],
            profiles=["cs"],
            write_last_success=True,
        )

        verify_rc = verify_published_s3.main(
            [
                "--bucket",
                bucket,
                "--run-id",
                run_id,
                "--prefix",
                prefix,
                "--verify-latest",
            ]
        )
        assert verify_rc == 0

        keys = []
        paginator = client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            for item in page.get("Contents", []):
                keys.append(item["Key"])

        run_keys = [
            f"{prefix}/runs/{run_id}/openai/cs/openai_ranked_jobs.cs.json",
            f"{prefix}/runs/{run_id}/openai/cs/openai_ranked_families.cs.json",
        ]
        latest_keys = [
            f"{prefix}/latest/openai/cs/openai_ranked_jobs.cs.json",
            f"{prefix}/latest/openai/cs/openai_ranked_families.cs.json",
        ]
        pointer_keys = [
            f"{prefix}/state/last_success.json",
            f"{prefix}/state/openai/cs/last_success.json",
        ]
        expected = sorted(run_keys + latest_keys + pointer_keys)
        assert sorted(keys) == expected

        body = client.get_object(Bucket=bucket, Key=run_keys[0])["Body"].read()
        assert body == (run_dir / "openai" / "cs" / "openai_ranked_jobs.cs.json").read_bytes()

        json_ct = client.get_object(Bucket=bucket, Key=run_keys[0])["ContentType"]
        assert json_ct == "application/json"

        latest_json_ct = client.get_object(Bucket=bucket, Key=latest_keys[0])["ContentType"]
        assert latest_json_ct == "application/json"
