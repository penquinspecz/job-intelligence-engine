from pathlib import Path

from scripts.score_jobs import _dedupe_jobs_for_scoring


def test_dedupe_jobs_collapses_same_job_id() -> None:
    jobs = [
        {"job_id": "same", "apply_url": "https://example.com/a", "jd_text": "short"},
        {"job_id": "same", "apply_url": "https://example.com/b", "jd_text": "much longer description"},
    ]
    out = _dedupe_jobs_for_scoring(jobs)
    assert len(out) == 1
    assert out[0]["job_id"] == "same"


def test_dedupe_jobs_preserves_provenance_and_selects_canonical() -> None:
    rich = {"job_id": "same", "apply_url": "https://example.com/rich", "jd_text": "x" * 200}
    poor = {"job_id": "same", "apply_url": "https://example.com/poor", "jd_text": "x"}
    out = _dedupe_jobs_for_scoring([poor, rich])
    assert len(out) == 1
    assert out[0]["apply_url"] == "https://example.com/rich"
    assert out[0]["duplicates"] == [{"apply_url": "https://example.com/poor"}]


def test_dedupe_jobs_deterministic_across_input_order() -> None:
    rich = {"job_id": "same", "apply_url": "https://example.com/rich", "jd_text": "x" * 200}
    poor = {"job_id": "same", "apply_url": "https://example.com/poor", "jd_text": "x"}
    out1 = _dedupe_jobs_for_scoring([poor, rich])
    out2 = _dedupe_jobs_for_scoring([rich, poor])
    assert out1 == out2
