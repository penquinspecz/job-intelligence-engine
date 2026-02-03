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
import scripts.verify_published_s3 as verify_published_s3
from ji_engine.utils.verification import compute_sha256_file


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _setup_run_dir(tmp_path: Path, run_id: str, *, write_files: bool = True) -> Path:
    run_dir = tmp_path / "state" / "runs" / publish_s3._sanitize_run_id(run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    ranked = data_dir / "openai_ranked_jobs.cs.json"
    shortlist = data_dir / "openai_shortlist.cs.md"
    if write_files:
        ranked.write_text("[]", encoding="utf-8")
        shortlist.write_text("hi", encoding="utf-8")
        ranked_sha = compute_sha256_file(ranked)
        shortlist_sha = compute_sha256_file(shortlist)
        ranked_bytes = ranked.stat().st_size
        shortlist_bytes = shortlist.stat().st_size
    else:
        ranked_sha = "x"
        shortlist_sha = "y"
        ranked_bytes = 2
        shortlist_bytes = 2
    verifiable = {
        "openai:cs:ranked_json": {
            "path": "openai_ranked_jobs.cs.json",
            "sha256": ranked_sha,
            "bytes": ranked_bytes,
            "hash_algo": "sha256",
        },
        "openai:cs:shortlist_md": {
            "path": "openai_shortlist.cs.md",
            "sha256": shortlist_sha,
            "bytes": shortlist_bytes,
            "hash_algo": "sha256",
        },
    }
    _write_json(run_dir / "run_report.json", {"run_id": run_id, "verifiable_artifacts": verifiable})
    return run_dir


def test_verify_published_s3_offline_expected_keys(tmp_path: Path, capsys) -> None:
    run_id = "2026-01-02T00:00:00Z"
    _setup_run_dir(tmp_path, run_id)
    verify_published_s3.RUN_METADATA_DIR = tmp_path / "state" / "runs"
    verify_published_s3.DATA_DIR = tmp_path / "data"

    code = verify_published_s3.main(
        [
            "--bucket",
            "bucket",
            "--run-id",
            run_id,
            "--prefix",
            "jobintel",
            "--verify-latest",
            "--offline",
            "--json",
        ]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    keys = [entry["s3_key"] for entry in payload["checked"]]
    assert keys == sorted(keys)
    assert any(key.endswith("openai_ranked_jobs.cs.json") for key in keys)
    assert any("/latest/openai/cs/" in key for key in keys)


def test_verify_published_s3_missing_verifiable_artifacts(tmp_path: Path, capsys) -> None:
    run_id = "2026-01-02T00:00:00Z"
    run_dir = tmp_path / "state" / "runs" / publish_s3._sanitize_run_id(run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    _write_json(run_dir / "run_report.json", {"run_id": run_id})
    verify_published_s3.RUN_METADATA_DIR = tmp_path / "state" / "runs"
    verify_published_s3.DATA_DIR = tmp_path / "data"

    code = verify_published_s3.main(
        [
            "--bucket",
            "bucket",
            "--run-id",
            run_id,
            "--prefix",
            "jobintel",
            "--offline",
            "--json",
        ]
    )
    assert code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False


def test_verify_published_s3_runtime_exception_returns_3(tmp_path: Path, monkeypatch, capsys) -> None:
    run_id = "2026-01-02T00:00:00Z"
    run_dir = _setup_run_dir(tmp_path, run_id)
    verify_published_s3.RUN_METADATA_DIR = tmp_path / "state" / "runs"
    verify_published_s3.DATA_DIR = tmp_path / "data"

    def boom(**_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(verify_published_s3, "_load_plan_entries", boom)
    code = verify_published_s3.main(
        [
            "--bucket",
            "bucket",
            "--run-id",
            run_id,
            "--prefix",
            "jobintel",
            "--offline",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert code == 3
    assert payload["ok"] is False


def test_verify_published_s3_missing_objects(tmp_path: Path, capsys) -> None:
    if boto3 is None or mock_s3 is None:  # pragma: no cover
        pytest.skip("boto3/moto not installed")
    run_id = "2026-01-02T00:00:00Z"
    run_dir = _setup_run_dir(tmp_path, run_id)
    verify_published_s3.RUN_METADATA_DIR = tmp_path / "state" / "runs"
    verify_published_s3.DATA_DIR = tmp_path / "data"

    with mock_s3():
        bucket = "bucket"
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket=bucket)
        key = f"jobintel/runs/{run_id}/openai_ranked_jobs.cs.json"
        client.put_object(Bucket=bucket, Key=key, Body=b"[]")

        code = verify_published_s3.main(
            [
                "--bucket",
                bucket,
                "--run-id",
                run_id,
                "--prefix",
                "jobintel",
                "--verify-latest",
                "--region",
                "us-east-1",
                "--json",
            ]
        )
        assert code == 2
        payload = json.loads(capsys.readouterr().out)
        missing = payload["missing"]
        assert any(missing_key.endswith("openai_shortlist.cs.md") for missing_key in missing)
        assert any("/latest/openai/cs/" in missing_key for missing_key in missing)


def test_verify_published_s3_offline_missing_local(tmp_path: Path, capsys) -> None:
    run_id = "2026-01-02T00:00:00Z"
    _setup_run_dir(tmp_path, run_id, write_files=False)
    verify_published_s3.RUN_METADATA_DIR = tmp_path / "state" / "runs"
    verify_published_s3.DATA_DIR = tmp_path / "data"

    code = verify_published_s3.main(
        [
            "--bucket",
            "bucket",
            "--run-id",
            run_id,
            "--prefix",
            "jobintel",
            "--offline",
            "--json",
        ]
    )
    assert code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["missing"]


def test_verify_published_s3_offline_modified_bytes(tmp_path: Path, capsys) -> None:
    run_id = "2026-01-02T00:00:00Z"
    _setup_run_dir(tmp_path, run_id)
    verify_published_s3.RUN_METADATA_DIR = tmp_path / "state" / "runs"
    verify_published_s3.DATA_DIR = tmp_path / "data"
    (tmp_path / "data" / "openai_ranked_jobs.cs.json").write_text("[1]", encoding="utf-8")

    code = verify_published_s3.main(
        [
            "--bucket",
            "bucket",
            "--run-id",
            run_id,
            "--prefix",
            "jobintel",
            "--offline",
            "--json",
        ]
    )
    assert code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["mismatched"]


def test_verify_published_s3_offline_plan_json_missing(tmp_path: Path, capsys) -> None:
    run_id = "2026-01-02T00:00:00Z"
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(
        json.dumps(
            [
                {
                    "logical_key": "openai:cs:ranked_json",
                    "local_path": "openai_ranked_jobs.cs.json",
                    "sha256": "x",
                    "bytes": 2,
                    "content_type": "application/json",
                    "s3_key": "jobintel/runs/2026-01-02T00:00:00Z/openai_ranked_jobs.cs.json",
                    "kind": "runs",
                }
            ]
        ),
        encoding="utf-8",
    )
    verify_published_s3.DATA_DIR = tmp_path / "data"
    verify_published_s3.DATA_DIR.mkdir(parents=True, exist_ok=True)

    code = verify_published_s3.main(
        [
            "--bucket",
            "bucket",
            "--run-id",
            run_id,
            "--prefix",
            "jobintel",
            "--offline",
            "--plan-json",
            str(plan_path),
            "--json",
        ]
    )
    assert code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["missing"]


def test_verify_published_s3_offline_skips_boto3(tmp_path: Path, monkeypatch, capsys) -> None:
    if boto3 is None:  # pragma: no cover
        pytest.skip("boto3 not installed")
    run_id = "2026-01-02T00:00:00Z"
    _setup_run_dir(tmp_path, run_id)
    verify_published_s3.RUN_METADATA_DIR = tmp_path / "state" / "runs"
    verify_published_s3.DATA_DIR = tmp_path / "data"

    def _boom(*args, **kwargs):
        raise AssertionError("boto3.client should not be called in offline mode")

    monkeypatch.setattr(boto3, "client", _boom)
    code = verify_published_s3.main(
        [
            "--bucket",
            "bucket",
            "--run-id",
            run_id,
            "--prefix",
            "jobintel",
            "--offline",
            "--json",
        ]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
