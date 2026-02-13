from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402


def _sanitize(run_id: str) -> str:
    return run_id.replace(":", "").replace("-", "").replace(".", "")


def test_dashboard_runs_empty(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("JOBINTEL_STATE_DIR", str(tmp_path / "state"))

    import importlib

    import ji_engine.config as config
    import ji_engine.dashboard.app as dashboard

    importlib.reload(config)
    dashboard = importlib.reload(dashboard)

    client = TestClient(dashboard.app)
    resp = client.get("/runs")
    assert resp.status_code == 200
    assert resp.json() == []


def test_dashboard_runs_populated(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("JOBINTEL_STATE_DIR", str(tmp_path / "state"))

    import importlib

    import ji_engine.config as config
    import ji_engine.dashboard.app as dashboard

    importlib.reload(config)
    dashboard = importlib.reload(dashboard)

    run_id = "2026-01-22T00:00:00Z"
    run_dir = config.RUN_METADATA_DIR / _sanitize(run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = run_dir / "openai_ranked_jobs.cs.json"
    artifact_path.write_text("[]", encoding="utf-8")
    index = {
        "run_id": run_id,
        "timestamp": run_id,
        "providers": {"openai": {"profiles": {"cs": {"diff_counts": {"new": 1, "changed": 0, "removed": 0}}}}},
        "artifacts": {artifact_path.name: artifact_path.relative_to(run_dir).as_posix()},
    }
    (run_dir / "index.json").write_text(json.dumps(index), encoding="utf-8")
    (run_dir / "run_report.json").write_text(
        json.dumps(
            {
                "semantic_enabled": True,
                "semantic_mode": "boost",
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "costs.json").write_text(
        json.dumps(
            {
                "embeddings_count": 2,
                "embeddings_estimated_tokens": 256,
                "ai_calls": 1,
                "ai_estimated_tokens": 32,
                "total_estimated_tokens": 288,
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "ai_insights.cs.json").write_text(
        json.dumps({"metadata": {"prompt_version": "weekly_insights_v3"}}),
        encoding="utf-8",
    )

    client = TestClient(dashboard.app)
    resp = client.get("/runs")
    assert resp.status_code == 200
    assert resp.json() and resp.json()[0]["run_id"] == run_id

    detail = client.get(f"/runs/{run_id}")
    assert detail.status_code == 200
    assert detail.json()["run_id"] == run_id
    assert detail.json()["semantic_enabled"] is True
    assert detail.json()["semantic_mode"] == "boost"
    assert detail.json()["ai_prompt_version"] == "weekly_insights_v3"
    assert detail.json()["cost_summary"]["total_estimated_tokens"] == 288

    artifact = client.get(f"/runs/{run_id}/artifact/{artifact_path.name}")
    assert artifact.status_code == 200
    assert artifact.headers["content-type"].startswith("application/json")

def test_dashboard_artifact_exfil_guard_rejects_invalid_mapping(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("JOBINTEL_STATE_DIR", str(tmp_path / "state"))

    import importlib

    import ji_engine.config as config
    import ji_engine.dashboard.app as dashboard

    importlib.reload(config)
    dashboard = importlib.reload(dashboard)

    run_id = "2026-01-22T00:00:00Z"
    run_dir = config.RUN_METADATA_DIR / _sanitize(run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    (config.STATE_DIR / "secret.txt").write_text("secret", encoding="utf-8")
    (run_dir / "index.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "timestamp": run_id,
                "artifacts": {"leak": "../secret.txt"},
            }
        ),
        encoding="utf-8",
    )

    client = TestClient(dashboard.app)
    resp = client.get(f"/runs/{run_id}/artifact/leak")
    assert resp.status_code == 500
    assert "invalid" in resp.json()["detail"].lower()


def test_dashboard_runs_populated_namespaced_candidate(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("JOBINTEL_STATE_DIR", str(tmp_path / "state"))

    import importlib

    import ji_engine.config as config
    import ji_engine.dashboard.app as dashboard

    importlib.reload(config)
    dashboard = importlib.reload(dashboard)

    run_id = "2026-01-22T00:00:00Z"
    run_dir = config.candidate_run_metadata_dir("alice") / _sanitize(run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "index.json").write_text(json.dumps({"run_id": run_id, "timestamp": run_id}), encoding="utf-8")

    client = TestClient(dashboard.app)
    resp = client.get("/runs", params={"candidate_id": "alice"})
    assert resp.status_code == 200
    assert resp.json() and resp.json()[0]["run_id"] == run_id


def test_dashboard_semantic_summary_endpoint(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("JOBINTEL_STATE_DIR", str(tmp_path / "state"))

    import importlib

    import ji_engine.config as config
    import ji_engine.dashboard.app as dashboard

    importlib.reload(config)
    dashboard = importlib.reload(dashboard)

    run_id = "2026-01-22T00:00:00Z"
    run_dir = config.RUN_METADATA_DIR / _sanitize(run_id)
    semantic_dir = run_dir / "semantic"
    semantic_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "index.json").write_text(json.dumps({"run_id": run_id, "timestamp": run_id}), encoding="utf-8")
    (semantic_dir / "semantic_summary.json").write_text(
        json.dumps({"enabled": True, "model_id": "deterministic-hash-v1"}),
        encoding="utf-8",
    )
    (semantic_dir / "scores_openai_cs.json").write_text(
        json.dumps({"entries": [{"provider": "openai", "profile": "cs", "job_id": "job-1"}]}),
        encoding="utf-8",
    )
    (semantic_dir / "scores_openai_se.json").write_text(
        json.dumps({"entries": [{"provider": "openai", "profile": "se", "job_id": "job-se"}]}),
        encoding="utf-8",
    )

    client = TestClient(dashboard.app)
    resp = client.get(f"/runs/{run_id}/semantic_summary/cs")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/json")
    payload = resp.json()
    assert payload["run_id"] == run_id
    assert payload["profile"] == "cs"
    assert payload["summary"]["enabled"] is True
    assert payload["entries"] == [{"provider": "openai", "profile": "cs", "job_id": "job-1"}]


def test_dashboard_latest_local(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("JOBINTEL_STATE_DIR", str(tmp_path / "state"))

    import importlib

    import ji_engine.config as config
    import ji_engine.dashboard.app as dashboard

    importlib.reload(config)
    dashboard = importlib.reload(dashboard)

    run_id = "2026-01-22T00:00:00Z"
    run_dir = config.candidate_run_metadata_dir("local") / _sanitize(run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "index.json").write_text(json.dumps({"run_id": run_id, "timestamp": run_id}), encoding="utf-8")
    last_success = {
        "run_id": run_id,
        "providers": ["openai"],
        "profiles": ["cs"],
    }
    (config.STATE_DIR / "last_success.json").write_text(json.dumps(last_success), encoding="utf-8")
    report = {
        "outputs_by_provider": {
            "openai": {
                "cs": {
                    "ranked_json": {"path": "openai_ranked_jobs.cs.json"},
                    "ranked_csv": {"path": "openai_ranked_jobs.cs.csv"},
                }
            }
        }
    }
    (run_dir / "run_report.json").write_text(json.dumps(report), encoding="utf-8")

    client = TestClient(dashboard.app)
    resp = client.get("/v1/latest")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["source"] == "local"
    assert payload["candidate_id"] == "local"
    assert payload["payload"]["run_id"] == run_id

    artifacts = client.get("/v1/artifacts/latest/openai/cs")
    assert artifacts.status_code == 200
    assert "openai_ranked_jobs.cs.json" in artifacts.json()["paths"][0]


def test_dashboard_runs_candidate_isolation(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("JOBINTEL_STATE_DIR", str(tmp_path / "state"))

    import importlib

    import ji_engine.config as config
    import ji_engine.dashboard.app as dashboard

    importlib.reload(config)
    dashboard = importlib.reload(dashboard)

    run_id = "2026-01-22T00:00:00Z"
    local_dir = config.candidate_run_metadata_dir("local") / _sanitize(run_id)
    alice_dir = config.candidate_run_metadata_dir("alice") / _sanitize(run_id)
    local_dir.mkdir(parents=True, exist_ok=True)
    alice_dir.mkdir(parents=True, exist_ok=True)
    (local_dir / "index.json").write_text(
        json.dumps({"run_id": run_id, "timestamp": "2026-01-22T00:00:00Z"}), encoding="utf-8"
    )
    (alice_dir / "index.json").write_text(
        json.dumps({"run_id": run_id, "timestamp": "2026-01-23T00:00:00Z"}), encoding="utf-8"
    )

    client = TestClient(dashboard.app)
    local_runs = client.get("/runs?candidate_id=local")
    alice_runs = client.get("/runs?candidate_id=alice")
    assert local_runs.status_code == 200
    assert alice_runs.status_code == 200
    assert local_runs.json()[0]["timestamp"] == "2026-01-22T00:00:00Z"
    assert alice_runs.json()[0]["timestamp"] == "2026-01-23T00:00:00Z"


def test_dashboard_invalid_candidate_id_rejected(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("JOBINTEL_STATE_DIR", str(tmp_path / "state"))

    import importlib

    import ji_engine.config as config
    import ji_engine.dashboard.app as dashboard

    importlib.reload(config)
    dashboard = importlib.reload(dashboard)

    client = TestClient(dashboard.app)
    resp = client.get("/runs?candidate_id=../../etc")
    assert resp.status_code == 400


def test_dashboard_latest_s3(monkeypatch) -> None:
    monkeypatch.setenv("JOBINTEL_S3_BUCKET", "proof-bucket")
    monkeypatch.setenv("JOBINTEL_S3_PREFIX", "jobintel")

    import importlib

    import ji_engine.config as config
    import ji_engine.dashboard.app as dashboard

    importlib.reload(config)
    dashboard = importlib.reload(dashboard)

    monkeypatch.setattr(
        dashboard.aws_runs,
        "read_last_success_state",
        lambda bucket, prefix, candidate_id="local": (
            {"run_id": "2026-01-01T00:00:00Z"},
            "ok",
            "state/last_success.json",
        ),
    )
    monkeypatch.setattr(dashboard, "_s3_list_keys", lambda bucket, prefix: [f"{prefix}key.json"])
    monkeypatch.setattr(dashboard, "_read_s3_json", lambda bucket, key: ({"run_id": "2026-01-01T00:00:00Z"}, "ok"))

    client = TestClient(dashboard.app)
    latest = client.get("/v1/latest")
    assert latest.status_code == 200
    assert latest.json()["source"] == "s3"

    artifacts = client.get("/v1/artifacts/latest/openai/cs")
    assert artifacts.status_code == 200
    assert artifacts.json()["keys"]

    run = client.get("/v1/runs/2026-01-01T00:00:00Z")
    assert run.status_code == 200
    assert run.json()["payload"]["run_id"] == "2026-01-01T00:00:00Z"


def test_dashboard_rejects_invalid_candidate_id(monkeypatch) -> None:
    monkeypatch.setenv("JOBINTEL_STATE_DIR", "/tmp/does-not-matter")

    import importlib

    import ji_engine.config as config
    import ji_engine.dashboard.app as dashboard

    importlib.reload(config)
    dashboard = importlib.reload(dashboard)

    client = TestClient(dashboard.app)
    resp = client.get("/runs", params={"candidate_id": "../escape"})
    assert resp.status_code == 400


def test_dashboard_runs_logs_corrupt_index(tmp_path: Path, monkeypatch, caplog) -> None:
    monkeypatch.setenv("JOBINTEL_STATE_DIR", str(tmp_path / "state"))

    import importlib

    import ji_engine.config as config
    import ji_engine.dashboard.app as dashboard

    importlib.reload(config)
    dashboard = importlib.reload(dashboard)

    run_id = "2026-01-22T00:00:00Z"
    run_dir = config.RUN_METADATA_DIR / _sanitize(run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "index.json").write_text("{invalid", encoding="utf-8")

    client = TestClient(dashboard.app)
    with caplog.at_level(logging.WARNING):
        resp = client.get("/runs")
    assert resp.status_code == 200
    assert resp.json() == []
    assert "Skipping run index" in caplog.text


def test_dashboard_run_detail_oversized_index_returns_413(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("JOBINTEL_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("JOBINTEL_DASHBOARD_MAX_JSON_BYTES", "64")

    import importlib

    import ji_engine.config as config
    import ji_engine.dashboard.app as dashboard

    importlib.reload(config)
    dashboard = importlib.reload(dashboard)

    run_id = "2026-01-22T00:00:00Z"
    run_dir = config.RUN_METADATA_DIR / _sanitize(run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    huge_index = {
        "run_id": run_id,
        "timestamp": run_id,
        "artifacts": {"a.json": "x" * 512},
    }
    (run_dir / "index.json").write_text(json.dumps(huge_index), encoding="utf-8")

    client = TestClient(dashboard.app)
    resp = client.get(f"/runs/{run_id}")
    assert resp.status_code == 413
    assert resp.json()["detail"] == "Run index payload too large"


def test_dashboard_latest_local_oversized_pointer_returns_413(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("JOBINTEL_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("JOBINTEL_DASHBOARD_MAX_JSON_BYTES", "64")

    import importlib

    import ji_engine.config as config
    import ji_engine.dashboard.app as dashboard

    importlib.reload(config)
    dashboard = importlib.reload(dashboard)

    oversized = {"run_id": "x" * 256}
    config.STATE_DIR.mkdir(parents=True, exist_ok=True)
    (config.STATE_DIR / "last_success.json").write_text(json.dumps(oversized), encoding="utf-8")

    client = TestClient(dashboard.app)
    resp = client.get("/v1/latest")
    assert resp.status_code == 413
    assert resp.json()["detail"] == "Local state payload too large"


def test_dashboard_semantic_summary_invalid_json_returns_500(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("JOBINTEL_STATE_DIR", str(tmp_path / "state"))

    import importlib

    import ji_engine.config as config
    import ji_engine.dashboard.app as dashboard

    importlib.reload(config)
    dashboard = importlib.reload(dashboard)

    run_id = "2026-01-22T00:00:00Z"
    run_dir = config.RUN_METADATA_DIR / _sanitize(run_id)
    semantic_dir = run_dir / "semantic"
    semantic_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "index.json").write_text(json.dumps({"run_id": run_id, "timestamp": run_id}), encoding="utf-8")
    (semantic_dir / "semantic_summary.json").write_text("{broken", encoding="utf-8")

    client = TestClient(dashboard.app)
    resp = client.get(f"/runs/{run_id}/semantic_summary/cs")
    assert resp.status_code == 500
    assert resp.json()["detail"] == "Semantic summary invalid JSON"
