import json
import logging
import sys
from pathlib import Path

import boto3
import pytest
from botocore.exceptions import ClientError

import scripts.publish_s3 as publish_s3
from ji_engine.utils.verification import compute_sha256_file


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


class DummyClient:
    def __init__(self):
        self.calls = []

    def upload_file(self, Filename, Bucket, Key, ExtraArgs=None):
        self.calls.append(("upload", Key, ExtraArgs or {}))

    def put_object(self, Bucket, Key, Body):
        self.calls.append(("put", Key))


def _setup_run(tmp_path: Path) -> tuple[str, Path]:
    run_id = "2026-01-02T00:00:00Z"
    run_dir = tmp_path / "state" / "runs" / publish_s3._sanitize_run_id(run_id)
    run_dir.mkdir(parents=True)
    provider_dir = run_dir / "openai" / "cs"
    provider_dir.mkdir(parents=True)
    ranked = provider_dir / "openai_ranked_jobs.cs.json"
    ranked.write_text("[]", encoding="utf-8")
    shortlist = provider_dir / "openai_shortlist.cs.md"
    shortlist.write_text("hi", encoding="utf-8")
    verifiable = {
        "openai:cs:ranked_json": {
            "path": "openai/cs/openai_ranked_jobs.cs.json",
            "sha256": compute_sha256_file(ranked),
            "hash_algo": "sha256",
        },
        "openai:cs:shortlist_md": {
            "path": "openai/cs/openai_shortlist.cs.md",
            "sha256": compute_sha256_file(shortlist),
            "hash_algo": "sha256",
        },
    }
    _write(
        run_dir / "run_report.json",
        {
            "run_id": run_id,
            "run_report_schema_version": 1,
            "verifiable_artifacts": verifiable,
            "providers": ["openai"],
            "profiles": ["cs"],
            "timestamps": {"ended_at": run_id},
        },
    )
    return run_id, run_dir


def test_publish_s3_uploads_runs_and_latest(tmp_path, monkeypatch):
    runs = tmp_path / "state" / "runs"
    monkeypatch.setattr(publish_s3, "RUN_METADATA_DIR", runs)
    run_id, _ = _setup_run(tmp_path)

    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIA_TEST_KEY")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "SUPER_SECRET")

    client = DummyClient()
    monkeypatch.setattr(boto3, "client", lambda *args, **kwargs: client)

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "publish_s3.py",
            "--bucket",
            "my-bucket",
            "--prefix",
            "jobintel",
            "--run_id",
            run_id,
        ],
    )

    publish_s3.main()
    keys = [call[1] for call in client.calls if call[0] == "upload"]
    assert sorted(keys) == sorted(
        [
            f"jobintel/runs/{run_id}/openai/cs/openai_ranked_jobs.cs.json",
            f"jobintel/runs/{run_id}/openai/cs/openai_shortlist.cs.md",
            "jobintel/latest/openai/cs/openai_ranked_jobs.cs.json",
            "jobintel/latest/openai/cs/openai_shortlist.cs.md",
        ]
    )
    content_types = [call[2].get("ContentType") for call in client.calls if call[0] == "upload"]
    assert any(ct == "application/json" for ct in content_types)
    assert any(ct == "text/markdown; charset=utf-8" for ct in content_types)
    put_keys = [call[1] for call in client.calls if call[0] == "put"]
    assert "jobintel/state/last_success.json" in put_keys
    assert "jobintel/state/openai/cs/last_success.json" in put_keys
    assert client.calls[-1][0] == "put"


def test_publish_s3_dry_run(monkeypatch, tmp_path, caplog):
    runs = tmp_path / "state" / "runs"
    monkeypatch.setattr(publish_s3, "RUN_METADATA_DIR", runs)
    run_id, _ = _setup_run(tmp_path)

    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("AWS_SECRET_ACCESS_KEY", raising=False)

    client = DummyClient()
    monkeypatch.setattr(boto3, "client", lambda *args, **kwargs: client)

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "publish_s3.py",
            "--bucket",
            "my-bucket",
            "--prefix",
            "jobintel",
            "--run_id",
            run_id,
            "--dry_run",
        ],
    )

    with caplog.at_level(logging.INFO):
        publish_s3.main()
    assert "dry-run" in caplog.text
    assert not client.calls


def test_publish_s3_disabled_without_bucket(monkeypatch, tmp_path, caplog):
    runs = tmp_path / "state" / "runs"
    monkeypatch.setattr(publish_s3, "RUN_METADATA_DIR", runs)
    run_id, _ = _setup_run(tmp_path)

    monkeypatch.delenv("JOBINTEL_S3_BUCKET", raising=False)
    monkeypatch.delenv("BUCKET", raising=False)

    with caplog.at_level(logging.INFO):
        meta = publish_s3.publish_run(
            run_id=run_id,
            bucket=None,
            prefix=None,
            dry_run=False,
            require_s3=False,
        )
    assert meta["status"] == "skipped"
    assert meta["reason"] == "missing_bucket"
    assert "S3 bucket unset" in caplog.text


def test_publish_s3_requires_bucket(monkeypatch, tmp_path, caplog):
    runs = tmp_path / "state" / "runs"
    monkeypatch.setattr(publish_s3, "RUN_METADATA_DIR", runs)
    run_id, _ = _setup_run(tmp_path)

    monkeypatch.delenv("JOBINTEL_S3_BUCKET", raising=False)
    monkeypatch.delenv("BUCKET", raising=False)
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "publish_s3.py",
            "--run_id",
            run_id,
            "--require_s3",
        ],
    )

    with caplog.at_level(logging.ERROR), pytest.raises(SystemExit) as exc:
        publish_s3.main()
    assert exc.value.code == 2
    assert "bucket is required" in caplog.text


def test_publish_s3_missing_creds_fails_without_dry_run(monkeypatch, tmp_path, caplog):
    runs = tmp_path / "state" / "runs"
    monkeypatch.setattr(publish_s3, "RUN_METADATA_DIR", runs)
    run_id, _ = _setup_run(tmp_path)

    monkeypatch.setenv("JOBINTEL_S3_BUCKET", "bucket")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("AWS_SECRET_ACCESS_KEY", raising=False)
    monkeypatch.delenv("AWS_CONTAINER_CREDENTIALS_RELATIVE_URI", raising=False)
    monkeypatch.delenv("AWS_CONTAINER_CREDENTIALS_FULL_URI", raising=False)
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    monkeypatch.delenv("AWS_SHARED_CREDENTIALS_FILE", raising=False)

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "publish_s3.py",
            "--bucket",
            "my-bucket",
            "--prefix",
            "jobintel",
            "--run_id",
            run_id,
        ],
    )

    with caplog.at_level(logging.ERROR), pytest.raises(SystemExit) as exc:
        publish_s3.main()
    assert exc.value.code == 2
    assert "credentials not detected" in caplog.text


def test_resolve_bucket_prefix_prefers_jobintel(monkeypatch) -> None:
    monkeypatch.setenv("JOBINTEL_S3_BUCKET", "jobintel-bucket")
    monkeypatch.setenv("BUCKET", "alias-bucket")
    monkeypatch.setenv("JOBINTEL_S3_PREFIX", "jobintel-prefix")
    monkeypatch.setenv("PREFIX", "alias-prefix")
    bucket, prefix = publish_s3._resolve_bucket_prefix(None, None)
    assert bucket == "jobintel-bucket"
    assert prefix == "jobintel-prefix"


def test_resolve_bucket_prefix_fallback_alias(monkeypatch) -> None:
    monkeypatch.delenv("JOBINTEL_S3_BUCKET", raising=False)
    monkeypatch.delenv("JOBINTEL_S3_PREFIX", raising=False)
    monkeypatch.setenv("BUCKET", "alias-bucket")
    monkeypatch.setenv("PREFIX", "alias-prefix")
    bucket, prefix = publish_s3._resolve_bucket_prefix(None, None)
    assert bucket == "alias-bucket"
    assert prefix == "alias-prefix"


def test_publish_s3_pointer_write_error(monkeypatch, tmp_path):
    runs = tmp_path / "state" / "runs"
    monkeypatch.setattr(publish_s3, "RUN_METADATA_DIR", runs)
    run_id, _ = _setup_run(tmp_path)

    class ErrorClient(DummyClient):
        def put_object(self, Bucket, Key, Body):
            if Key.endswith("state/last_success.json"):
                raise ClientError(
                    {"Error": {"Code": "AccessDenied", "Message": "denied"}}, "PutObject"
                )
            super().put_object(Bucket=Bucket, Key=Key, Body=Body)

    client = ErrorClient()
    monkeypatch.setattr(boto3, "client", lambda *args, **kwargs: client)

    meta = publish_s3.publish_run(
        run_id=run_id,
        bucket="my-bucket",
        prefix="jobintel",
        dry_run=False,
        require_s3=False,
        write_last_success=True,
    )
    assert meta["status"] == "error"
    assert meta["pointer_write"]["global"] == "error"


def test_publish_s3_logs_target_bucket_prefix(monkeypatch, tmp_path, caplog):
    runs = tmp_path / "state" / "runs"
    monkeypatch.setattr(publish_s3, "RUN_METADATA_DIR", runs)
    run_id, _ = _setup_run(tmp_path)

    client = DummyClient()
    monkeypatch.setattr(boto3, "client", lambda *args, **kwargs: client)

    with caplog.at_level(logging.INFO):
        publish_s3.publish_run(
            run_id=run_id,
            bucket="target-bucket",
            prefix="jobintel",
            dry_run=True,
            require_s3=False,
        )
    assert "S3 publish target: s3://target-bucket/jobintel" in caplog.text


def test_publish_s3_dry_run_plan_is_deterministic(tmp_path: Path, monkeypatch, caplog) -> None:
    runs = tmp_path / "state" / "runs"
    monkeypatch.setattr(publish_s3, "RUN_METADATA_DIR", runs)
    run_id, _ = _setup_run(tmp_path)

    with caplog.at_level(logging.INFO):
        publish_s3.publish_run(
            run_id=run_id,
            bucket=None,
            prefix="jobintel",
            dry_run=True,
            require_s3=False,
        )
    keys = []
    for line in caplog.text.splitlines():
        if "dry-run:" not in line or "s3://" not in line:
            continue
        keys.append(line.split("s3://", 1)[1])
    assert keys == sorted(keys)


def test_publish_s3_requires_verifiable_artifacts(tmp_path: Path, monkeypatch) -> None:
    runs = tmp_path / "state" / "runs"
    monkeypatch.setattr(publish_s3, "RUN_METADATA_DIR", runs)
    run_id = "2026-01-02T00:00:00Z"
    run_dir = runs / publish_s3._sanitize_run_id(run_id)
    run_dir.mkdir(parents=True)
    _write(run_dir / "run_report.json", {"run_id": run_id, "run_report_schema_version": 1})
    with pytest.raises(SystemExit) as exc:
        publish_s3.publish_run(
            run_id=run_id,
            bucket=None,
            prefix="jobintel",
            dry_run=True,
            require_s3=False,
        )
    assert exc.value.code == 2
