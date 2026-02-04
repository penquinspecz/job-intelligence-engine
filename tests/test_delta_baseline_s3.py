import importlib
import json

import ji_engine.config as config
import scripts.run_daily as run_daily_module


def test_delta_summary_uses_s3_baseline(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    state_dir = tmp_path / "state"
    monkeypatch.setenv("JOBINTEL_DATA_DIR", str(data_dir))
    monkeypatch.setenv("JOBINTEL_STATE_DIR", str(state_dir))
    monkeypatch.setenv("S3_PUBLISH_ENABLED", "1")
    monkeypatch.setenv("JOBINTEL_S3_BUCKET", "bucket")
    monkeypatch.setenv("JOBINTEL_S3_PREFIX", "jobintel")
    importlib.reload(config)
    run_daily = importlib.reload(run_daily_module)

    provider = "openai"
    profile = "cs"
    current_ranked = data_dir / f"{provider}_ranked_jobs.{profile}.json"
    current_ranked.parent.mkdir(parents=True, exist_ok=True)
    payload = [{"job_id": "1", "title": "A", "apply_url": "https://example.com"}]
    current_ranked.write_text(json.dumps(payload), encoding="utf-8")
    labeled = data_dir / f"{provider}_labeled_jobs.json"
    labeled.write_text(json.dumps(payload), encoding="utf-8")

    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(json.dumps(payload), encoding="utf-8")

    def fake_state(bucket, prefix):
        return {
            "run_id": "2026-01-01T00:00:00Z",
            "run_path": "jobintel/runs/2026-01-01T00:00:00Z/",
            "provider_profiles": {f"{provider}:{profile}": "2026-01-01T00:00:00Z"},
        }

    monkeypatch.setattr(
        run_daily, "read_last_success_state", lambda *args, **kwargs: (fake_state(None, None), "ok", "key")
    )
    monkeypatch.setattr(
        run_daily,
        "read_provider_last_success_state",
        lambda *args, **kwargs: (None, "not_found", "key"),
    )
    monkeypatch.setattr(
        run_daily,
        "download_baseline_ranked",
        lambda *args, **kwargs: baseline_path,
    )

    summary = run_daily._build_delta_summary("2026-01-02T00:00:00Z", [provider], [profile])
    entry = summary["provider_profile"][provider][profile]
    assert entry["baseline_source"] == "state_file"
    assert entry["baseline_resolved"] is True
    assert entry["new_job_count"] == 0


def test_s3_baseline_prefers_provider_pointer(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    state_dir = tmp_path / "state"
    monkeypatch.setenv("JOBINTEL_DATA_DIR", str(data_dir))
    monkeypatch.setenv("JOBINTEL_STATE_DIR", str(state_dir))
    monkeypatch.setenv("S3_PUBLISH_ENABLED", "1")
    monkeypatch.setenv("JOBINTEL_S3_BUCKET", "bucket")
    monkeypatch.setenv("JOBINTEL_S3_PREFIX", "jobintel")
    importlib.reload(config)
    run_daily = importlib.reload(run_daily_module)

    provider = "openai"
    profile = "cs"
    current_ranked = data_dir / f"{provider}_ranked_jobs.{profile}.json"
    current_ranked.parent.mkdir(parents=True, exist_ok=True)
    payload = [{"job_id": "1", "title": "A", "apply_url": "https://example.com"}]
    current_ranked.write_text(json.dumps(payload), encoding="utf-8")
    labeled = data_dir / f"{provider}_labeled_jobs.json"
    labeled.write_text(json.dumps(payload), encoding="utf-8")

    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(json.dumps(payload), encoding="utf-8")

    provider_state = {
        "run_id": "2026-01-02T00:00:00Z",
        "run_path": "jobintel/runs/2026-01-02T00:00:00Z/",
    }
    global_state = {
        "run_id": "2026-01-01T00:00:00Z",
        "run_path": "jobintel/runs/2026-01-01T00:00:00Z/",
    }
    monkeypatch.setattr(
        run_daily,
        "read_provider_last_success_state",
        lambda *args, **kwargs: (provider_state, "ok", "key"),
    )
    monkeypatch.setattr(
        run_daily,
        "read_last_success_state",
        lambda *args, **kwargs: (global_state, "ok", "key"),
    )

    used = {}

    def fake_download(*args, **kwargs):
        used["run_id"] = args[2]
        return baseline_path

    monkeypatch.setattr(run_daily, "download_baseline_ranked", fake_download)

    summary = run_daily._build_delta_summary("2026-01-03T00:00:00Z", [provider], [profile])
    entry = summary["provider_profile"][provider][profile]
    assert entry["baseline_run_id"] == provider_state["run_id"]
    assert used["run_id"] == provider_state["run_id"]
