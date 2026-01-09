import json
import sys
from pathlib import Path

import scripts.report_changes as report_changes
import scripts.run_daily as run_daily


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _create_history_run(tmp_dir: Path, run_id: str, profile: str, jobs):
    archive_dir = run_daily._history_run_dir(run_id, profile)
    for job in jobs:
        job.setdefault("score", 0)
    ranked_path = archive_dir / run_daily.ranked_jobs_json(profile).name
    _write_json(ranked_path, jobs)

    run_meta_path = run_daily._run_metadata_path(run_id)
    run_meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_payload = {
        "run_id": run_id,
        "profiles": [profile],
        "stages": {},
        "diff_counts": {},
    }
    _write_json(run_meta_path, meta_payload)

    history_meta = archive_dir / "run_metadata.json"
    _write_json(history_meta, meta_payload)


def test_report_changes(tmp_path, capsys, monkeypatch):
    history_dir = tmp_path / "state" / "history"
    monkeypatch.setattr(run_daily, "HISTORY_DIR", history_dir)
    monkeypatch.setattr(report_changes, "HISTORY_DIR", history_dir)
    monkeypatch.setattr(run_daily, "HISTORY_DIR", history_dir)

    run_id1 = "2026-01-01T00:00:00Z"
    run_id2 = "2026-01-02T00:00:00Z"
    profile = "cs"
    run_daily._history_run_dir(run_id1, profile).mkdir(parents=True, exist_ok=True)
    run_daily._history_run_dir(run_id2, profile).mkdir(parents=True, exist_ok=True)

    jobs_prev = [
        {"title": "Role A", "apply_url": "https://example.com/a", "score": 100},
        {"title": "Role B", "apply_url": "https://example.com/b", "score": 90},
        {"title": "Role C", "apply_url": "https://example.com/c", "score": 80},
    ]
    jobs_curr = [
        {"title": "Role A", "apply_url": "https://example.com/a", "score": 110},
        {"title": "Role D", "apply_url": "https://example.com/d", "score": 70},
    ]

    _create_history_run(tmp_path, run_id1, profile, jobs_prev)
    _create_history_run(tmp_path, run_id2, profile, jobs_curr)

    monkeypatch.setattr(
        sys,
        "argv",
        ["report_changes.py", "--profile", profile, "--run_id", run_id2, "--limit", "2"],
    )
    report_changes.main()
    output = capsys.readouterr().out

    assert "Changes since last run for profile cs" in output
    assert "New" in output
    assert "- Role D — https://example.com/d" in output
    assert "Changed" in output
    assert "removed" in output.lower()


def test_previous_run_selection_prefers_history(tmp_path, monkeypatch):
    history_dir = tmp_path / "state" / "history"
    monkeypatch.setattr(report_changes, "HISTORY_DIR", history_dir)
    monkeypatch.setattr(run_daily, "HISTORY_DIR", history_dir)
    profile = "cs"
    run_id_b = "2026-01-02T00:00:00Z"
    run_id_a = "2026-01-01T00:00:00Z"

    _create_history_run(tmp_path, run_id_b, profile, [{"title": "Later", "apply_url": "https://later"}])
    _create_history_run(tmp_path, run_id_a, profile, [{"title": "Earlier", "apply_url": "https://earlier"}])

    selected = report_changes._select_run(profile, run_id_b)
    assert selected["run_id"] == run_id_b
    prev = report_changes._get_previous_run(profile, run_id_b)
    assert prev is not None
    assert prev["run_id"] == run_id_a

    assert report_changes._get_previous_run(profile, run_id_a) is None
