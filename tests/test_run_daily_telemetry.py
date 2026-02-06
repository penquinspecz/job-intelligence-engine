from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import scripts.run_daily as run_daily


def _write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj), encoding="utf-8")


def _output_dir(data_dir: Path) -> Path:
    out = data_dir / "ashby_cache"
    out.mkdir(parents=True, exist_ok=True)
    return out


def _fake_run_factory(ai_path: Path):
    counters = {"ai": 0, "score": 0, "other": 0}

    def _fake_run(cmd, stage: str):
        cmd_str = " ".join(cmd)
        if "run_ai_augment.py" in cmd_str:
            _write_json(ai_path, [{"ai": True, "title": "t"}])
            counters["ai"] += 1
        elif "score_jobs.py" in cmd_str:

            def _arg_value(flag: str) -> Path | None:
                if flag in cmd:
                    return Path(cmd[cmd.index(flag) + 1])
                return None

            ranked_json = _arg_value("--out_json")
            ranked_csv = _arg_value("--out_csv")
            ranked_families = _arg_value("--out_families")
            shortlist_md = _arg_value("--out_md")
            top_md = _arg_value("--out_md_top_n")

            if ranked_json:
                _write_json(ranked_json, [{"title": "t", "score": 1}])
            if ranked_csv:
                ranked_csv.parent.mkdir(parents=True, exist_ok=True)
                ranked_csv.write_text("title,score\n", encoding="utf-8")
            if ranked_families:
                _write_json(ranked_families, [])
            if shortlist_md:
                shortlist_md.parent.mkdir(parents=True, exist_ok=True)
                shortlist_md.write_text("# Shortlist\n", encoding="utf-8")
            if top_md:
                top_md.parent.mkdir(parents=True, exist_ok=True)
                top_md.write_text("# Top\n", encoding="utf-8")
            counters["score"] += 1
        else:
            counters["other"] += 1

    return _fake_run, counters


def test_short_circuit_writes_last_run(tmp_path, monkeypatch):
    monkeypatch.setattr(run_daily, "DATA_DIR", tmp_path)
    output_dir = _output_dir(tmp_path)
    raw = output_dir / "openai_raw_jobs.json"
    labeled = output_dir / "openai_labeled_jobs.json"
    enriched = output_dir / "openai_enriched_jobs.json"
    for p in (raw, labeled):
        _write_json(p, [])
    _write_json(enriched, [{"apply_url": "u1", "title": "t", "enrich_status": "enriched", "score": 0}])

    monkeypatch.setattr(run_daily, "RAW_JOBS_JSON", raw)
    monkeypatch.setattr(run_daily, "LABELED_JOBS_JSON", labeled)
    monkeypatch.setattr(run_daily, "ENRICHED_JOBS_JSON", enriched)

    last_run = tmp_path / "state" / "last_run.json"
    lock_path = tmp_path / "state" / "lock"
    monkeypatch.setattr(run_daily, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(run_daily, "LAST_RUN_JSON", last_run)
    monkeypatch.setattr(run_daily, "LAST_SUCCESS_JSON", tmp_path / "state" / "last_success.json")
    monkeypatch.setattr(run_daily, "LOCK_PATH", lock_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    h_raw = run_daily._hash_file(raw)
    h_lab = run_daily._hash_file(labeled)
    h_enr = run_daily._hash_file(enriched)
    _write_json(last_run, {"hashes": {"raw": h_raw, "labeled": h_lab, "enriched": h_enr}})

    # Ensure ranked artifacts exist so short-circuit can skip scoring.
    ranked_json = output_dir / "openai_ranked_jobs.cs.json"
    ranked_csv = output_dir / "openai_ranked_jobs.cs.csv"
    ranked_families = output_dir / "openai_ranked_families.cs.json"
    shortlist_md = output_dir / "openai_shortlist.cs.md"
    _write_json(ranked_json, [{"title": "t", "score": 1}])
    ranked_csv.write_text("title,score\n", encoding="utf-8")
    _write_json(ranked_families, [])
    shortlist_md.write_text("# Shortlist\n", encoding="utf-8")

    monkeypatch.setattr(run_daily, "_run", lambda *a, **k: None)
    monkeypatch.setattr(run_daily, "USE_SUBPROCESS", False)

    monkeypatch.setattr(sys, "argv", ["run_daily.py", "--no_subprocess"])
    rc = run_daily.main()
    assert rc == 0
    data = json.loads(last_run.read_text())
    assert data["status"] == "short_circuit"
    assert data["hashes"]["raw"] == h_raw
    assert not (tmp_path / "state" / "last_success.json").exists()


def test_last_run_written_on_success(tmp_path, monkeypatch):
    monkeypatch.setattr(run_daily, "DATA_DIR", tmp_path)
    output_dir = _output_dir(tmp_path)
    raw = output_dir / "openai_raw_jobs.json"
    labeled = output_dir / "openai_labeled_jobs.json"
    enriched = output_dir / "openai_enriched_jobs.json"
    _write_json(raw, [{"x": 1}])
    _write_json(labeled, [{"y": 2}])
    _write_json(enriched, [{"apply_url": "u1", "title": "t", "enrich_status": "enriched", "score": 0}])

    monkeypatch.setattr(run_daily, "RAW_JOBS_JSON", raw)
    monkeypatch.setattr(run_daily, "LABELED_JOBS_JSON", labeled)
    monkeypatch.setattr(run_daily, "ENRICHED_JOBS_JSON", enriched)

    last_run = tmp_path / "state" / "last_run.json"
    lock_path = tmp_path / "state" / "lock"
    monkeypatch.setattr(run_daily, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(run_daily, "LAST_RUN_JSON", last_run)
    monkeypatch.setattr(run_daily, "LAST_SUCCESS_JSON", tmp_path / "state" / "last_success.json")
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
    pointer_path = tmp_path / "state" / "last_success.json"
    assert pointer_path.exists()
    pointer = json.loads(pointer_path.read_text())
    assert pointer["run_id"] is not None
    assert "artifacts" in pointer


def test_run_daily_emits_run_id_line(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(run_daily, "DATA_DIR", tmp_path)
    output_dir = _output_dir(tmp_path)
    raw = output_dir / "openai_raw_jobs.json"
    labeled = output_dir / "openai_labeled_jobs.json"
    enriched = output_dir / "openai_enriched_jobs.json"
    _write_json(raw, [{"x": 1}])
    _write_json(labeled, [{"y": 2}])
    _write_json(enriched, [{"apply_url": "u1", "title": "t", "enrich_status": "enriched", "score": 0}])

    monkeypatch.setattr(run_daily, "RAW_JOBS_JSON", raw)
    monkeypatch.setattr(run_daily, "LABELED_JOBS_JSON", labeled)
    monkeypatch.setattr(run_daily, "ENRICHED_JOBS_JSON", enriched)
    monkeypatch.setattr(run_daily, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(run_daily, "LAST_RUN_JSON", tmp_path / "state" / "last_run.json")
    monkeypatch.setattr(run_daily, "LAST_SUCCESS_JSON", tmp_path / "state" / "last_success.json")
    monkeypatch.setattr(run_daily, "LOCK_PATH", tmp_path / "state" / "lock")
    (tmp_path / "state").mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(run_daily, "_run", lambda *a, **k: None)
    monkeypatch.setattr(run_daily, "USE_SUBPROCESS", False)
    monkeypatch.setattr(run_daily, "_resolve_profiles", lambda args: [])
    monkeypatch.setattr(run_daily, "_utcnow_iso", lambda: "2026-01-02T00:00:00Z")

    monkeypatch.setattr(sys, "argv", ["run_daily.py", "--no_subprocess", "--profile", "cs"])
    rc = run_daily.main()
    assert rc == 0
    out = capsys.readouterr().out
    assert "JOBINTEL_RUN_ID=2026-01-02T00:00:00Z" in out


def test_ai_runs_and_scoring_when_needed(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(run_daily, "DATA_DIR", tmp_path)
    output_dir = _output_dir(tmp_path)
    raw = output_dir / "openai_raw_jobs.json"
    labeled = output_dir / "openai_labeled_jobs.json"
    enriched = output_dir / "openai_enriched_jobs.json"
    _write_json(raw, [{"x": 1}])
    _write_json(labeled, [{"y": 2}])
    _write_json(enriched, [{"apply_url": "u1", "title": "t", "enrich_status": "enriched", "score": 0}])

    ai_path = enriched.with_name("openai_enriched_jobs_ai.json")
    ranked = output_dir / "openai_ranked_jobs.cs.json"
    last_run = tmp_path / "state" / "last_run.json"
    lock_path = tmp_path / "state" / "lock"

    monkeypatch.setattr(run_daily, "RAW_JOBS_JSON", raw)
    monkeypatch.setattr(run_daily, "LABELED_JOBS_JSON", labeled)
    monkeypatch.setattr(run_daily, "ENRICHED_JOBS_JSON", enriched)
    monkeypatch.setattr(run_daily, "LAST_RUN_JSON", last_run)
    monkeypatch.setattr(run_daily, "LOCK_PATH", lock_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(run_daily, "STATE_DIR", tmp_path / "state")

    fake_run, counters = _fake_run_factory(ai_path)
    monkeypatch.setattr(run_daily, "_run", fake_run)
    monkeypatch.setattr(run_daily, "_resolve_profiles", lambda args: ["cs"])
    monkeypatch.setattr(run_daily, "USE_SUBPROCESS", False)

    monkeypatch.setattr(sys, "argv", ["run_daily.py", "--no_subprocess", "--ai", "--profile", "cs"])
    rc = run_daily.main()
    assert rc == 0
    data = json.loads(last_run.read_text())
    assert data["status"] == "success"
    assert data.get("ai_requested") is True
    assert data.get("ai_ran") is True
    assert data.get("ai_output_hash") is not None
    assert ai_path.exists()
    assert counters["ai"] == 1
    assert counters["score"] == 1
    lock_path.unlink(missing_ok=True)

    # Second run should short-circuit (no changes)
    fake_run2, counters2 = _fake_run_factory(ai_path)
    monkeypatch.setattr(run_daily, "_run", fake_run2)
    monkeypatch.setattr(sys, "argv", ["run_daily.py", "--no_subprocess", "--ai", "--profile", "cs"])
    rc = run_daily.main()
    assert rc == 0
    data2 = json.loads(last_run.read_text())
    assert data2["status"] == "short_circuit"
    assert data2.get("ai_requested") is True
    assert data2.get("ai_ran") is False
    assert data2.get("ai_output_hash") is not None
    assert data2.get("ai_output_mtime") is not None
    assert counters2["ai"] == 0
    assert counters2["score"] == 0
    lock_path.unlink(missing_ok=True)

    # If AI file is deleted, --ai must NOT short-circuit (should regenerate)
    ai_path.unlink(missing_ok=True)
    fake_run_del, counters_del = _fake_run_factory(ai_path)
    monkeypatch.setattr(run_daily, "_run", fake_run_del)
    monkeypatch.setattr(sys, "argv", ["run_daily.py", "--no_subprocess", "--ai", "--profile", "cs"])
    rc = run_daily.main()
    assert rc == 0
    assert counters_del["ai"] == 1
    assert counters_del["score"] == 1
    lock_path.unlink(missing_ok=True)

    # If ranked is older than AI file, should re-run scoring
    # Make ranked artificially older.
    ai_ts = ai_path.stat().st_mtime
    os.utime(ranked, (ai_ts - 10, ai_ts - 10))
    fake_run_old, counters_old = _fake_run_factory(ai_path)
    monkeypatch.setattr(run_daily, "_run", fake_run_old)
    monkeypatch.setattr(sys, "argv", ["run_daily.py", "--no_subprocess", "--ai", "--profile", "cs"])
    rc = run_daily.main()
    assert rc == 0
    assert counters_old["score"] == 1
    lock_path.unlink(missing_ok=True)

    # If AI file changes, scoring should run again
    _write_json(ai_path, [{"ai": True, "title": "changed"}])
    fake_run3, counters3 = _fake_run_factory(ai_path)
    monkeypatch.setattr(run_daily, "_run", fake_run3)
    monkeypatch.setattr(sys, "argv", ["run_daily.py", "--no_subprocess", "--ai", "--profile", "cs"])
    rc = run_daily.main()
    assert rc == 0
    data3 = json.loads(last_run.read_text())
    assert data3["status"] == "success"
    assert counters3["score"] == 1
