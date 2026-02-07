from __future__ import annotations

import json
from pathlib import Path

import scripts.run_daily as run_daily


def test_apply_user_state_to_alerts_filters_new_and_ignored() -> None:
    alerts = {
        "counts": {"new": 2, "removed": 2, "score_changes": 2, "title_or_location_changes": 1},
        "new_jobs": [{"job_id": "new-a"}, {"job_id": "new-b"}],
        "removed_jobs": ["old-a", "old-b"],
        "score_changes": [{"job_id": "chg-a"}, {"job_id": "chg-b"}],
        "title_or_location_changes": [{"job_id": "chg-a"}],
    }
    out = run_daily._apply_user_state_to_alerts(
        alerts,
        suppress_new_ids={"new-b"},
        ignored_ids={"old-b", "chg-b"},
    )
    assert [item["job_id"] for item in out["new_jobs"]] == ["new-a"]
    assert out["removed_jobs"] == ["old-a"]
    assert [item["job_id"] for item in out["score_changes"]] == ["chg-a"]
    assert [item["job_id"] for item in out["title_or_location_changes"]] == ["chg-a"]
    assert out["counts"] == {"new": 1, "removed": 1, "score_changes": 1, "title_or_location_changes": 1}


def test_user_state_sets_collect_counts_and_suppression(tmp_path: Path, monkeypatch) -> None:
    user_state_dir = tmp_path / "state" / "user_state"
    user_state_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(run_daily, "USER_STATE_DIR", user_state_dir)

    (user_state_dir / "cs.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "jobs": {
                    "a": {"status": "ignore"},
                    "b": {"status": "applied"},
                    "c": {"status": "saved"},
                    "d": {"status": "interviewing"},
                },
            }
        ),
        encoding="utf-8",
    )
    jobs = [
        {"job_id": "a", "title": "A"},
        {"job_id": "b", "title": "B"},
        {"job_id": "c", "title": "C"},
        {"job_id": "d", "title": "D"},
        {"job_id": "e", "title": "E"},
    ]
    _, counts, ignored_ids, suppress_new_ids = run_daily._user_state_sets("cs", jobs)

    assert counts == {"ignore": 1, "saved": 1, "applied": 1, "interviewing": 1}
    assert ignored_ids == {"a"}
    assert suppress_new_ids == {"a", "b", "d"}


def test_annotate_and_deprioritize_items_marks_status_and_pushes_down_applied_interviewing() -> None:
    items = [
        {"job_id": "a", "title": "A", "score": 95},
        {"job_id": "b", "title": "B", "score": 99},
        {"job_id": "c", "title": "C", "score": 91},
        {"job_id": "d", "title": "D", "score": 88},
    ]
    state_map = {
        "b": {"status": "applied"},
        "c": {"status": "interviewing"},
        "d": {"status": "saved"},
    }

    out = run_daily._annotate_and_deprioritize_items(items, state_map)

    assert [item["job_id"] for item in out] == ["a", "d", "b", "c"]
    assert out[1]["user_state_status"] == "saved"
    assert out[2]["user_state_status"] == "applied"
    assert out[3]["user_state_status"] == "interviewing"
