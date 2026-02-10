from __future__ import annotations

import json
from pathlib import Path

from jobintel.safety.diff import build_safety_diff_report

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
