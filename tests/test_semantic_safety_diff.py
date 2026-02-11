from __future__ import annotations

import json
from pathlib import Path

from jobintel.safety.diff import build_safety_diff_report, load_jobs_from_path

FIXTURES = Path(__file__).parent / "fixtures" / "safety_diff"


def _load(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def test_safety_diff_report_matches_golden() -> None:
    baseline = _load(FIXTURES / "baseline.json")
    candidate = _load(FIXTURES / "candidate.json")
    baseline_path = "tests/fixtures/safety_diff/baseline.json"
    candidate_path = "tests/fixtures/safety_diff/candidate.json"
    report = build_safety_diff_report(
        baseline,
        candidate,
        baseline_path=baseline_path,
        candidate_path=candidate_path,
        top_n=5,
    )
    expected = _load(FIXTURES / "report.json")
    assert report == expected


def test_load_jobs_from_run_report_supports_outputs_by_profile(tmp_path: Path) -> None:
    ranked = tmp_path / "ranked.json"
    ranked.write_text(json.dumps([{"job_id": "j1", "title": "Role"}]) + "\n", encoding="utf-8")
    run_report = {
        "run_report_schema_version": 1,
        "providers": ["openai"],
        "profiles": ["cs"],
        "outputs_by_profile": {"cs": {"ranked_json": {"path": str(ranked)}}},
    }
    report_path = tmp_path / "run_report.json"
    report_path.write_text(json.dumps(run_report) + "\n", encoding="utf-8")
    jobs = load_jobs_from_path(report_path)
    assert jobs == [{"job_id": "j1", "title": "Role"}]


def test_safety_diff_counts_duplicate_job_ids() -> None:
    baseline = [
        {"job_id": "dup", "title": "Engineer I", "apply_url": "https://example.com/a"},
    ]
    candidate = [
        {"job_id": "dup", "title": "Engineer I", "apply_url": "https://example.com/a"},
        {"job_id": "dup", "title": "Engineer II", "apply_url": "https://example.com/b"},
    ]
    report = build_safety_diff_report(
        baseline,
        candidate,
        baseline_path="baseline.json",
        candidate_path="candidate.json",
        top_n=5,
    )
    assert report["counts"]["new"] == 1
    assert report["counts"]["removed"] == 0
