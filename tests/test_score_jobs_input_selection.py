from __future__ import annotations

import importlib
import json
import os
import sys
from pathlib import Path


def _write_job(path: Path, title: str) -> None:
    path.write_text(json.dumps([{"title": title, "apply_url": "http://example.com", "score": 1}]), encoding="utf-8")


def test_score_jobs_respects_in_path_without_prefer_ai(tmp_path, monkeypatch, caplog) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    # Required supporting files
    (data_dir / "candidate_profile.json").write_text('{"skills": [], "roles": []}', encoding="utf-8")
    (data_dir / "profiles.json").write_text('{"cs": {"role_band_multipliers": {}, "profile_weights": {}}}', encoding="utf-8")
    # Inputs: both enriched and AI-enriched exist; without --prefer_ai we must keep requested path
    enriched = data_dir / "openai_enriched_jobs.json"
    ai_enriched = data_dir / "openai_enriched_jobs_ai.json"
    _write_job(enriched, "Enriched Title")
    _write_job(ai_enriched, "AI Title")

    monkeypatch.setenv("JOBINTEL_DATA_DIR", str(data_dir))
    monkeypatch.setenv("JOBINTEL_STATE_DIR", str(tmp_path / "state"))
    # Reload modules to pick up new DATA_DIR
    import ji_engine.config as config
    import scripts.score_jobs as score_jobs

    config = importlib.reload(config)
    score_jobs = importlib.reload(score_jobs)

    # Force default profile config path to our temp file
    monkeypatch.setattr(score_jobs, "load_profiles", lambda path: json.loads((data_dir / "profiles.json").read_text()))

    caplog.set_level("INFO")
    monkeypatch.setattr(sys, "argv", ["score_jobs.py", "--in_path", str(enriched), "--out_json", str(tmp_path / "out.json"), "--out_csv", str(tmp_path / "out.csv"), "--out_families", str(tmp_path / "out_families.json"), "--out_md", str(tmp_path / "out.md"), "--profiles", str(data_dir / "profiles.json")])
    rc = score_jobs.main()
    assert rc is None or rc == 0
    # Should not have switched to AI without --prefer_ai
    assert "Using AI-enriched input" not in caplog.text
    out_json = json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))
    assert out_json and out_json[0]["title"] == "Enriched Title"


def test_score_jobs_prefers_ai_when_flag_set(tmp_path, monkeypatch, caplog) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "candidate_profile.json").write_text('{"skills": [], "roles": []}', encoding="utf-8")
    (data_dir / "profiles.json").write_text('{"cs": {"role_band_multipliers": {}, "profile_weights": {}}}', encoding="utf-8")
    enriched = data_dir / "openai_enriched_jobs.json"
    ai_enriched = data_dir / "openai_enriched_jobs_ai.json"
    _write_job(enriched, "Enriched Title")
    _write_job(ai_enriched, "AI Title")

    monkeypatch.setenv("JOBINTEL_DATA_DIR", str(data_dir))
    monkeypatch.setenv("JOBINTEL_STATE_DIR", str(tmp_path / "state"))

    import ji_engine.config as config
    import scripts.score_jobs as score_jobs

    config = importlib.reload(config)
    score_jobs = importlib.reload(score_jobs)
    monkeypatch.setattr(score_jobs, "load_profiles", lambda path: json.loads((data_dir / "profiles.json").read_text()))

    caplog.set_level("INFO")
    monkeypatch.setattr(sys, "argv", ["score_jobs.py", "--in_path", str(enriched), "--prefer_ai", "--out_json", str(tmp_path / "out.json"), "--out_csv", str(tmp_path / "out.csv"), "--out_families", str(tmp_path / "out_families.json"), "--out_md", str(tmp_path / "out.md"), "--profiles", str(data_dir / "profiles.json")])
    rc = score_jobs.main()
    assert rc is None or rc == 0
    assert "Using AI-enriched input" in caplog.text
    out_json = json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))
    assert out_json and out_json[0]["title"] == "AI Title"


def test_score_jobs_default_ignores_ai_file(tmp_path, monkeypatch, caplog) -> None:
    """
    Default mode (no --prefer_ai) must NOT auto-switch to AI-enriched input even if present.
    """
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "candidate_profile.json").write_text('{"skills": [], "roles": []}', encoding="utf-8")
    (data_dir / "profiles.json").write_text('{"cs": {"role_band_multipliers": {}, "profile_weights": {}}}', encoding="utf-8")
    enriched = data_dir / "openai_enriched_jobs.json"
    ai_enriched = data_dir / "openai_enriched_jobs_ai.json"
    _write_job(enriched, "Enriched Title")
    _write_job(ai_enriched, "AI Title")

    monkeypatch.setenv("JOBINTEL_DATA_DIR", str(data_dir))
    monkeypatch.setenv("JOBINTEL_STATE_DIR", str(tmp_path / "state"))

    import ji_engine.config as config
    import scripts.score_jobs as score_jobs

    config = importlib.reload(config)
    score_jobs = importlib.reload(score_jobs)
    monkeypatch.setattr(score_jobs, "load_profiles", lambda path: json.loads((data_dir / "profiles.json").read_text()))

    caplog.set_level("INFO")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "score_jobs.py",
            "--in_path",
            str(enriched),
            "--out_json",
            str(tmp_path / "out.json"),
            "--out_csv",
            str(tmp_path / "out.csv"),
            "--out_families",
            str(tmp_path / "out_families.json"),
            "--out_md",
            str(tmp_path / "out.md"),
            "--profiles",
            str(data_dir / "profiles.json"),
        ],
    )
    rc = score_jobs.main()
    assert rc is None or rc == 0
    # Should not log AI-enriched usage
    assert "Using AI-enriched input" not in caplog.text
    out_json = json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))
    assert out_json and out_json[0]["title"] == "Enriched Title"
