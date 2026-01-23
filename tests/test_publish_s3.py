import json
import logging
import sys
from pathlib import Path

import boto3
import pytest
from botocore.exceptions import ClientError

import scripts.publish_s3 as publish_s3


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


class DummyClient:
    def __init__(self):
        self.calls = []

    def upload_file(self, Filename, Bucket, Key):
        self.calls.append(("upload", Key))

    def put_object(self, Bucket, Key, Body):
        self.calls.append(("put", Key))


def _setup_run(tmp_path: Path) -> tuple[str, Path]:
    run_id = "2026-01-02T00:00:00Z"
    run_dir = tmp_path / "state" / "runs" / publish_s3._sanitize_run_id(run_id)
    run_dir.mkdir(parents=True)
    provider_dir = run_dir / "openai" / "cs"
    provider_dir.mkdir(parents=True)
    (provider_dir / "ranked.json").write_text("[]", encoding="utf-8")
    (provider_dir / "shortlist.md").write_text("hi", encoding="utf-8")
    _write(
        run_dir / "index.json",
        {
            "run_id": run_id,
            "providers": {"openai": {"profiles": {"cs": {"diff_counts": {"new": 1, "changed": 0, "removed": 0}}}}},
            "artifacts": {},
        },
    )
    return run_id, run_dir


def test_publish_s3_uploads_runs_and_latest(tmp_path, monkeypatch):
    runs = tmp_path / "state" / "runs"
    monkeypatch.setattr(publish_s3, "RUN_METADATA_DIR", runs)
    run_id, _ = _setup_run(tmp_path)

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
    assert any(key.startswith(f"jobintel/runs/{run_id}/") for key in keys)
    assert any(key.startswith("jobintel/latest/openai/cs/") for key in keys)
    put_keys = [call[1] for call in client.calls if call[0] == "put"]
    assert "jobintel/state/last_success.json" in put_keys
    assert "jobintel/state/openai/cs/last_success.json" in put_keys
    assert client.calls[-1][0] == "put"


def test_publish_s3_dry_run(monkeypatch, tmp_path, caplog):
    runs = tmp_path / "state" / "runs"
    monkeypatch.setattr(publish_s3, "RUN_METADATA_DIR", runs)
    run_id, _ = _setup_run(tmp_path)

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
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "publish_s3.py",
            "--run_id",
            run_id,
        ],
    )

    with caplog.at_level(logging.INFO):
        publish_s3.main()
    assert "S3 bucket unset" in caplog.text


def test_publish_s3_requires_bucket(monkeypatch, tmp_path):
    runs = tmp_path / "state" / "runs"
    monkeypatch.setattr(publish_s3, "RUN_METADATA_DIR", runs)
    run_id, _ = _setup_run(tmp_path)

    monkeypatch.delenv("JOBINTEL_S3_BUCKET", raising=False)
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

    with pytest.raises(SystemExit) as exc:
        publish_s3.main()
    assert str(exc.value) == "2"


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
