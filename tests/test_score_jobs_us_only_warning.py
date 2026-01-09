from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path


def _write_jobs(path: Path, jobs: list[dict]) -> None:
    path.write_text(json.dumps(jobs), encoding="utf-8")


def test_us_only_warns_when_all_filtered_out(tmp_path, monkeypatch, caplog) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True, exist_ok=True)

    enriched = data_dir / "openai_enriched_jobs.json"
    # Job without location info so US filter will drop it
    _write_jobs(enriched, [{"title": "No Location", "apply_url": "http://example.com", "score": 1}])

    (data_dir / "candidate_profile.json").write_text('{"skills": [], "roles": []}', encoding="utf-8")
    (data_dir / "profiles.json").write_text('{"cs": {"role_band_multipliers": {}, "profile_weights": {}}}', encoding="utf-8")

    monkeypatch.setenv("JOBINTEL_DATA_DIR", str(data_dir))
    monkeypatch.setenv("JOBINTEL_STATE_DIR", str(state_dir))

    import ji_engine.config as config
    import scripts.score_jobs as score_jobs

    config = importlib.reload(config)
    score_jobs = importlib.reload(score_jobs)
    monkeypatch.setattr(score_jobs, "load_profiles", lambda path: json.loads((data_dir / "profiles.json").read_text()))

    caplog.set_level("WARNING")
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
            "--us_only",
        ],
    )

    rc = score_jobs.main()
    assert rc is None or rc == 0
    assert "US-only filter removed all jobs" in caplog.text
    assert "did you pass labeled input instead of enriched" in caplog.text.lower()
