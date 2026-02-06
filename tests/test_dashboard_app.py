from __future__ import annotations

import json
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
    import jobintel.dashboard.app as dashboard

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
    import jobintel.dashboard.app as dashboard

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

    client = TestClient(dashboard.app)
    resp = client.get("/runs")
    assert resp.status_code == 200
    assert resp.json() and resp.json()[0]["run_id"] == run_id

    detail = client.get(f"/runs/{run_id}")
    assert detail.status_code == 200
    assert detail.json()["run_id"] == run_id

    artifact = client.get(f"/runs/{run_id}/artifact/{artifact_path.name}")
    assert artifact.status_code == 200
    assert artifact.headers["content-type"].startswith("application/json")


def test_dashboard_latest_local(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("JOBINTEL_STATE_DIR", str(tmp_path / "state"))

    import importlib

    import ji_engine.config as config
    import jobintel.dashboard.app as dashboard

    importlib.reload(config)
    dashboard = importlib.reload(dashboard)

    run_id = "2026-01-22T00:00:00Z"
    run_dir = config.RUN_METADATA_DIR / _sanitize(run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    last_success = {
        "run_id": run_id,
        "providers": ["openai"],
        "profiles": ["cs"],
    }
    (config.STATE_DIR / "last_success.json").write_text(
        json.dumps(last_success), encoding="utf-8"
    )
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
    assert payload["payload"]["run_id"] == run_id

    artifacts = client.get("/v1/artifacts/latest/openai/cs")
    assert artifacts.status_code == 200
    assert "openai_ranked_jobs.cs.json" in artifacts.json()["paths"][0]


def test_dashboard_latest_s3(monkeypatch) -> None:
    monkeypatch.setenv("JOBINTEL_S3_BUCKET", "proof-bucket")
    monkeypatch.setenv("JOBINTEL_S3_PREFIX", "jobintel")

    import importlib

    import ji_engine.config as config
    import jobintel.dashboard.app as dashboard

    importlib.reload(config)
    dashboard = importlib.reload(dashboard)

    monkeypatch.setattr(
        dashboard.aws_runs,
        "read_last_success_state",
        lambda bucket, prefix: ({"run_id": "2026-01-01T00:00:00Z"}, "ok", "state/last_success.json"),
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
