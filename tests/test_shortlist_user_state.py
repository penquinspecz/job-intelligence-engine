import json
import logging
from pathlib import Path

import scripts.score_jobs as score_jobs
from ji_engine.utils.job_identity import job_identity


def test_shortlist_user_state_missing_yields_no_annotations(tmp_path: Path, monkeypatch) -> None:
    user_state_dir = tmp_path / "state" / "user_state"
    monkeypatch.setattr(score_jobs, "USER_STATE_DIR", user_state_dir)

    scored = [
        {
            "title": "Role A",
            "apply_url": "https://example.com/a",
            "score": 90,
            "role_band": "L4",
        }
    ]
    out_path = tmp_path / "openai_shortlist.cs.md"

    score_jobs.write_shortlist_md(scored, out_path, min_score=0)

    content = out_path.read_text(encoding="utf-8")
    assert "[APPLIED]" not in content
    assert "Note:" not in content


def test_shortlist_user_state_marks_job(tmp_path: Path, monkeypatch) -> None:
    user_state_dir = tmp_path / "state" / "user_state"
    user_state_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(score_jobs, "USER_STATE_DIR", user_state_dir)

    job = {
        "title": "Role A",
        "apply_url": "https://example.com/a",
        "score": 90,
        "role_band": "L4",
    }
    state = {
        "schema_version": 1,
        "jobs": {
            job_identity(job): {
                "status": "applied",
                "notes": "Reached out to recruiter and waiting on response.",
            }
        },
    }
    (user_state_dir / "cs.json").write_text(json.dumps(state), encoding="utf-8")
    out_path = tmp_path / "openai_shortlist.cs.md"

    score_jobs.write_shortlist_md([job], out_path, min_score=0)

    content = out_path.read_text(encoding="utf-8")
    assert "[applied]" in content
    assert "Note:" in content


def test_shortlist_user_state_ignore_suppresses_job(tmp_path: Path, monkeypatch) -> None:
    user_state_dir = tmp_path / "state" / "user_state"
    user_state_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(score_jobs, "USER_STATE_DIR", user_state_dir)

    job = {
        "title": "Role A",
        "apply_url": "https://example.com/a",
        "score": 90,
        "role_band": "L4",
    }
    state = {
        "schema_version": 1,
        "jobs": {
            job_identity(job): {
                "status": "ignore",
            }
        },
    }
    (user_state_dir / "cs.json").write_text(json.dumps(state), encoding="utf-8")
    out_path = tmp_path / "openai_shortlist.cs.md"

    score_jobs.write_shortlist_md([job], out_path, min_score=0)
    content = out_path.read_text(encoding="utf-8")
    assert "Role A" not in content


def test_shortlist_user_state_invalid_json_warns_and_continues(tmp_path: Path, monkeypatch, caplog) -> None:
    user_state_dir = tmp_path / "state" / "user_state"
    user_state_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(score_jobs, "USER_STATE_DIR", user_state_dir)
    (user_state_dir / "cs.json").write_text("{bad-json", encoding="utf-8")

    caplog.set_level(logging.WARNING)
    job = {
        "title": "Role A",
        "apply_url": "https://example.com/a",
        "score": 90,
        "role_band": "L4",
    }
    out_path = tmp_path / "openai_shortlist.cs.md"
    score_jobs.write_shortlist_md([job], out_path, min_score=0)

    content = out_path.read_text(encoding="utf-8")
    assert "Role A" in content
    assert any("invalid user_state JSON" in record.message for record in caplog.records)
