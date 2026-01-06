from __future__ import annotations

import json
import sys
from pathlib import Path

import scripts.run_daily as run_daily


def _write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj), encoding="utf-8")


def test_short_circuit_writes_last_run(tmp_path, monkeypatch):
    raw = tmp_path / "raw.json"
    labeled = tmp_path / "labeled.json"
    enriched = tmp_path / "enriched.json"
    for p in (raw, labeled):
        _write_json(p, [])
    _write_json(enriched, [{"apply_url": "u1", "title": "t", "enrich_status": "enriched", "score": 0}])

    monkeypatch.setattr(run_daily, "RAW_JOBS_JSON", raw)
    monkeypatch.setattr(run_daily, "LABELED_JOBS_JSON", labeled)
    monkeypatch.setattr(run_daily, "ENRICHED_JOBS_JSON", enriched)

    last_run = tmp_path / "state" / "last_run.json"
    lock_path = tmp_path / "state" / "lock"
    monkeypatch.setattr(run_daily, "LAST_RUN_JSON", last_run)
    monkeypatch.setattr(run_daily, "LOCK_PATH", lock_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    h_raw = run_daily._hash_file(raw)
    h_lab = run_daily._hash_file(labeled)
    h_enr = run_daily._hash_file(enriched)
    _write_json(last_run, {"hashes": {"raw": h_raw, "labeled": h_lab, "enriched": h_enr}})

    monkeypatch.setattr(run_daily, "_run", lambda *a, **k: None)
    monkeypatch.setattr(run_daily, "USE_SUBPROCESS", False)

    monkeypatch.setattr(sys, "argv", ["run_daily.py", "--no_subprocess"])
    rc = run_daily.main()
    assert rc == 0
    data = json.loads(last_run.read_text())
    assert data["status"] == "short_circuit"
    assert data["hashes"]["raw"] == h_raw


def test_last_run_written_on_success(tmp_path, monkeypatch):
    raw = tmp_path / "raw.json"
    labeled = tmp_path / "labeled.json"
    enriched = tmp_path / "enriched.json"
    _write_json(raw, [{"x": 1}])
    _write_json(labeled, [{"y": 2}])
    _write_json(enriched, [{"apply_url": "u1", "title": "t", "enrich_status": "enriched", "score": 0}])

    monkeypatch.setattr(run_daily, "RAW_JOBS_JSON", raw)
    monkeypatch.setattr(run_daily, "LABELED_JOBS_JSON", labeled)
    monkeypatch.setattr(run_daily, "ENRICHED_JOBS_JSON", enriched)

    last_run = tmp_path / "state" / "last_run.json"
    lock_path = tmp_path / "state" / "lock"
    monkeypatch.setattr(run_daily, "LAST_RUN_JSON", last_run)
    monkeypatch.setattr(run_daily, "LOCK_PATH", lock_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    # ensure prev hashes differ
    _write_json(last_run, {"hashes": {"raw": "x", "labeled": "y", "enriched": "z"}})

    monkeypatch.setattr(run_daily, "_run", lambda *a, **k: None)
    monkeypatch.setattr(run_daily, "USE_SUBPROCESS", False)
    monkeypatch.setattr(run_daily, "_resolve_profiles", lambda args: [])

    monkeypatch.setattr(sys, "argv", ["run_daily.py", "--no_subprocess", "--profile", "cs"])
    rc = run_daily.main()
    assert rc == 0
    data = json.loads(last_run.read_text())
    assert data["status"] == "success"
    assert data["hashes"]["raw"] == run_daily._hash_file(raw)

