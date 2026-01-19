from pathlib import Path

from scripts import run_daily


def _job(apply_url: str, title: str, score: int, description: str, location: str = "Test", team: str = "Ops") -> dict:
    return {
        "apply_url": apply_url,
        "title": title,
        "location": location,
        "team": team,
        "score": score,
        "description_text": description,
    }


def test_changelog_counts(tmp_path: Path) -> None:
    prev_jobs = [
        _job("https://example.com/a", "A Role", 100, "alpha"),
        _job("https://example.com/b", "B Role", 90, "beta"),
        _job("https://example.com/c", "C Role", 80, "gamma"),
    ]
    curr_jobs = [
        _job("https://example.com/a", "A Role", 100, "alpha"),  # unchanged
        _job("https://example.com/b", "B Role", 95, "beta-new"),  # score & desc changed
        _job("https://example.com/d", "D Role", 70, "delta"),  # new job
    ]

    prev_path = tmp_path / "prev.json"
    curr_path = tmp_path / "curr.json"
    run_daily._write_json(prev_path, prev_jobs)
    run_daily._write_json(curr_path, curr_jobs)

    prev_loaded = run_daily._read_json(prev_path)
    curr_loaded = run_daily._read_json(curr_path)

    new_jobs, changed_jobs, removed_jobs, _changed_fields = run_daily._diff(prev_loaded, curr_loaded)

    assert len(new_jobs) == 1
    assert len(changed_jobs) == 1
    assert len(removed_jobs) == 1


def test_changelog_uses_job_id_identity(tmp_path: Path) -> None:
    prev_jobs = [
        _job("https://example.com/a", "A Role", 100, "alpha"),
    ]
    prev_jobs[0]["job_id"] = "job-1"
    curr_jobs = [
        _job("https://example.com/a", "A Role", 100, "alpha"),
    ]
    curr_jobs[0]["job_id"] = "job-2"

    prev_path = tmp_path / "prev.json"
    curr_path = tmp_path / "curr.json"
    run_daily._write_json(prev_path, prev_jobs)
    run_daily._write_json(curr_path, curr_jobs)

    prev_loaded = run_daily._read_json(prev_path)
    curr_loaded = run_daily._read_json(curr_path)

    new_jobs, changed_jobs, removed_jobs, _changed_fields = run_daily._diff(prev_loaded, curr_loaded)

    assert len(new_jobs) == 1
    assert len(changed_jobs) == 0
    assert len(removed_jobs) == 1
