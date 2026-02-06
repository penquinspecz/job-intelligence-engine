import json
from pathlib import Path

import scripts.set_job_status as set_job_status


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_set_job_status_create_update_remove(tmp_path: Path, monkeypatch) -> None:
    user_state_dir = tmp_path / "state" / "user_state"
    monkeypatch.setattr(set_job_status, "USER_STATE_DIR", user_state_dir)

    rc = set_job_status.main(["--profile", "cs", "--job-id", "job-1", "--status", "applied", "--note", "first note"])
    assert rc == 0
    path = user_state_dir / "cs.json"
    assert path.exists()
    data = json.loads(_read(path))
    assert data["schema_version"] == 1
    assert data["jobs"]["job-1"]["status"] == "applied"
    assert data["jobs"]["job-1"]["notes"] == "first note"

    rc = set_job_status.main(["--profile", "cs", "--job-id", "job-1", "--status", "interviewing", "--note", "updated"])
    assert rc == 0
    data = json.loads(_read(path))
    assert data["jobs"]["job-1"]["status"] == "interviewing"
    assert data["jobs"]["job-1"]["notes"] == "updated"

    rc = set_job_status.main(["--profile", "cs", "--job-id", "job-1", "--status", "none"])
    assert rc == 0
    data = json.loads(_read(path))
    assert data == {"jobs": {}, "schema_version": 1}


def test_set_job_status_deterministic_format(tmp_path: Path, monkeypatch) -> None:
    user_state_dir = tmp_path / "state" / "user_state"
    monkeypatch.setattr(set_job_status, "USER_STATE_DIR", user_state_dir)

    set_job_status.main(["--profile", "cs", "--job-id", "b", "--status", "saved"])
    set_job_status.main(["--profile", "cs", "--job-id", "a", "--status", "ignore"])
    first = _read(user_state_dir / "cs.json")

    set_job_status.main(["--profile", "cs", "--job-id", "a", "--status", "ignore"])
    second = _read(user_state_dir / "cs.json")

    assert first == second
