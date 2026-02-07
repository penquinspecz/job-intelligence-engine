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


def test_shortlist_user_state_deprioritizes_applied_and_interviewing(tmp_path: Path, monkeypatch) -> None:
    user_state_dir = tmp_path / "state" / "user_state"
    user_state_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(score_jobs, "USER_STATE_DIR", user_state_dir)

    applied_job = {
        "job_id": "a",
        "title": "Applied",
        "apply_url": "https://example.com/a",
        "score": 99,
        "role_band": "L5",
    }
    neutral_job = {
        "job_id": "b",
        "title": "Neutral",
        "apply_url": "https://example.com/b",
        "score": 90,
        "role_band": "L4",
    }
    interviewing_job = {
        "job_id": "c",
        "title": "Interviewing",
        "apply_url": "https://example.com/c",
        "score": 95,
        "role_band": "L4",
    }
    state = {
        "schema_version": 1,
        "jobs": {
            "a": {"status": "applied"},
            "c": {"status": "interviewing"},
        },
    }
    (user_state_dir / "cs.json").write_text(json.dumps(state), encoding="utf-8")
    out_path = tmp_path / "openai_shortlist.cs.md"

    score_jobs.write_shortlist_md([applied_job, neutral_job, interviewing_job], out_path, min_score=0)
    content = out_path.read_text(encoding="utf-8")

    assert content.index("## Neutral") < content.index("## Applied")
    assert content.index("## Applied") < content.index("## Interviewing")
    assert "[applied]" in content
    assert "[interviewing]" in content


def test_shortlist_user_state_deterministic_and_state_diff_is_explainable(tmp_path: Path, monkeypatch) -> None:
    user_state_dir = tmp_path / "state" / "user_state"
    user_state_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(score_jobs, "USER_STATE_DIR", user_state_dir)
    out_path = tmp_path / "openai_shortlist.cs.md"
    jobs = [
        {"job_id": "a", "title": "Role A", "apply_url": "https://example.com/a", "score": 95, "role_band": "L4"},
        {"job_id": "b", "title": "Role B", "apply_url": "https://example.com/b", "score": 91, "role_band": "L4"},
    ]

    state_v1 = {"schema_version": 1, "jobs": {"a": {"status": "applied"}}}
    (user_state_dir / "cs.json").write_text(json.dumps(state_v1), encoding="utf-8")
    score_jobs.write_shortlist_md(jobs, out_path, min_score=0)
    first = out_path.read_text(encoding="utf-8")
    score_jobs.write_shortlist_md(jobs, out_path, min_score=0)
    second = out_path.read_text(encoding="utf-8")
    assert first == second

    state_v2 = {"schema_version": 1, "jobs": {"a": {"status": "ignore"}}}
    (user_state_dir / "cs.json").write_text(json.dumps(state_v2), encoding="utf-8")
    score_jobs.write_shortlist_md(jobs, out_path, min_score=0)
    third = out_path.read_text(encoding="utf-8")
    assert "Role A" not in third
    assert "Role B" in third
