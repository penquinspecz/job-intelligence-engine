from __future__ import annotations

import json
import sys
from pathlib import Path

import scripts.run_daily as run_daily


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_run_daily_writes_semantic_summary_when_disabled(tmp_path: Path, monkeypatch) -> None:
    data_dir = tmp_path / "data"
    output_dir = data_dir / "ashby_cache"
    state_dir = tmp_path / "state"
    output_dir.mkdir(parents=True, exist_ok=True)
    state_dir.mkdir(parents=True, exist_ok=True)

    _write_json(data_dir / "candidate_profile.json", {"roles": ["cs"]})
    _write_json(output_dir / "openai_raw_jobs.json", [{"id": 1}])
    _write_json(output_dir / "openai_labeled_jobs.json", [{"id": 1}])
    _write_json(output_dir / "openai_enriched_jobs.json", [{"id": 1}])

    monkeypatch.setenv("SEMANTIC_ENABLED", "0")
    monkeypatch.setattr(run_daily, "DATA_DIR", data_dir)
    monkeypatch.setattr(run_daily, "STATE_DIR", state_dir)
    monkeypatch.setattr(run_daily, "RUN_METADATA_DIR", state_dir / "runs")
    monkeypatch.setattr(run_daily, "LAST_RUN_JSON", state_dir / "last_run.json")
    monkeypatch.setattr(run_daily, "LAST_SUCCESS_JSON", state_dir / "last_success.json")
    monkeypatch.setattr(run_daily, "LOCK_PATH", state_dir / "lock")
    monkeypatch.setattr(run_daily, "_run", lambda *a, **k: None)
    monkeypatch.setattr(run_daily, "_resolve_profiles", lambda args: [])
    monkeypatch.setattr(run_daily, "_utcnow_iso", lambda: "2026-01-02T00:00:00Z")

    run_daily.USE_SUBPROCESS = False
    monkeypatch.setattr(sys, "argv", ["run_daily.py", "--no_subprocess", "--profile", "cs", "--no_post"])

    rc = run_daily.main()
    assert rc == 0

    summary_path = state_dir / "runs" / "20260102T000000Z" / "semantic" / "semantic_summary.json"
    assert summary_path.exists()
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["enabled"] is False
    assert summary["skipped_reason"] == "semantic_disabled"
