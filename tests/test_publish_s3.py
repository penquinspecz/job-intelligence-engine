import json
import sys
from pathlib import Path

import boto3
import logging
import pytest
import scripts.publish_s3 as publish_s3


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


class DummyClient:
    def __init__(self):
        self.calls = []

    def upload_file(self, Filename, Bucket, Key):
        self.calls.append((Filename, Bucket, Key))


def test_publish_s3_uploads(tmp_path, monkeypatch):
    history = tmp_path / "state" / "history"
    runs = tmp_path / "state" / "runs"
    monkeypatch.setattr(publish_s3, "HISTORY_DIR", history)
    monkeypatch.setattr(publish_s3, "RUN_METADATA_DIR", runs)

    run_id = "2026-01-02T00:00:00Z"
    profile = "cs"
    data_dir = history / "2026-01-02" / "20260102T000000Z" / profile
    data_dir.mkdir(parents=True)
    file = data_dir / "ranked.json"
    file.write_text("[]", encoding="utf-8")

    _write(runs / "run.json", {"run_id": run_id, "profiles": [profile], "stages": {}, "diff_counts": {}})

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
            "--profile",
            profile,
            "--run_id",
            run_id,
        ],
    )

    publish_s3.main()

    assert client.calls
    assert client.calls[0][1] == "my-bucket"
    assert "2026-01-02/20260102T000000Z/cs/ranked.json" in client.calls[0][2]


def test_publish_s3_dry_run(monkeypatch, tmp_path, caplog):
    history = tmp_path / "state" / "history"
    runs = tmp_path / "state" / "runs"
    monkeypatch.setattr(publish_s3, "HISTORY_DIR", history)
    monkeypatch.setattr(publish_s3, "RUN_METADATA_DIR", runs)

    run_id = "2026-01-02T00:00:00Z"
    profile = "cs"
    data_dir = history / "2026-01-02" / "20260102T000000Z" / profile
    data_dir.mkdir(parents=True)
    file = data_dir / "ranked.json"
    file.write_text("[]", encoding="utf-8")
    _write(runs / "run.json", {"run_id": run_id, "profiles": [profile], "stages": {}, "diff_counts": {}})

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
            "--profile",
            profile,
            "--run_id",
            run_id,
            "--dry_run",
        ],
    )

    with caplog.at_level(logging.INFO):
        publish_s3.main()
    assert "dry-run" in caplog.text
    assert not client.calls


def test_publish_s3_rejects_outside_history(monkeypatch, tmp_path):
    history = tmp_path / "state" / "history"
    runs = tmp_path / "state" / "runs"
    monkeypatch.setattr(publish_s3, "HISTORY_DIR", history)
    monkeypatch.setattr(publish_s3, "RUN_METADATA_DIR", runs)

    run_id = "2026-01-02T00:00:00Z"
    profile = "cs"
    history_dir = history / "2026-01-02" / "20260102T000000Z" / profile
    history_dir.mkdir(parents=True)
    (history_dir / "ranked.json").write_text("[]", encoding="utf-8")

    embed_cache = tmp_path / "state" / "embed_cache.json"
    embed_cache.parent.mkdir(parents=True, exist_ok=True)
    embed_cache.write_text("[]", encoding="utf-8")

    _write(runs / "run.json", {"run_id": run_id, "profiles": [profile], "stages": {}, "diff_counts": {}})

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "publish_s3.py",
            "--bucket",
            "my-bucket",
            "--prefix",
            "jobintel",
            "--profile",
            profile,
            "--run_id",
            run_id,
        ],
    )

    # force collect_artifacts to include embed_cache by pointing base_dir there
    monkeypatch.setattr(publish_s3, "_history_run_dir", lambda run_id, profile: embed_cache.parent)

    with pytest.raises(SystemExit) as exc:
        publish_s3.main()
    assert "outside state/history" in str(exc.value)
