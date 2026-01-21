from pathlib import Path

from jobintel.delta import compute_delta


def _write_json(path: Path, data) -> None:
    import json

    path.write_text(json.dumps(data), encoding="utf-8")


def test_delta_baseline_missing(tmp_path: Path) -> None:
    current_labeled = tmp_path / "openai_labeled_jobs.json"
    current_ranked = tmp_path / "openai_ranked_jobs.cs.json"

    _write_json(current_labeled, [{"apply_url": "a", "title": "A"}])
    _write_json(current_ranked, [{"apply_url": "a", "title": "A"}])

    delta = compute_delta(
        current_labeled,
        current_ranked,
        None,
        None,
        "openai",
        "cs",
    )

    assert delta["labeled_total"] == 1
    assert delta["ranked_total"] == 1
    assert delta["new_job_count"] == 0
    assert delta["removed_job_count"] == 0
    assert delta["changed_job_count"] == 0
    assert delta["unchanged_job_count"] == 0


def test_delta_new_removed_changed_unchanged(tmp_path: Path) -> None:
    current_labeled = tmp_path / "openai_labeled_jobs.json"
    current_ranked = tmp_path / "openai_ranked_jobs.cs.json"
    baseline_ranked = tmp_path / "baseline_ranked.json"

    baseline_jobs = [
        {"apply_url": "a", "title": "Alpha", "location": "NY"},
        {"apply_url": "b", "title": "Beta", "location": "SF"},
        {"apply_url": "c", "title": "Gamma", "location": "Remote"},
    ]
    current_jobs = [
        {"apply_url": "a", "title": "Alpha", "location": "NY"},
        {"apply_url": "c", "title": "Gamma v2", "location": "Remote"},
        {"apply_url": "d", "title": "Delta", "location": "LA"},
    ]

    _write_json(current_labeled, current_jobs)
    _write_json(current_ranked, current_jobs)
    _write_json(baseline_ranked, baseline_jobs)

    delta = compute_delta(
        current_labeled,
        current_ranked,
        None,
        baseline_ranked,
        "openai",
        "cs",
    )

    assert delta["labeled_total"] == 3
    assert delta["ranked_total"] == 3
    assert delta["new_job_count"] == 1
    assert delta["removed_job_count"] == 1
    assert delta["changed_job_count"] == 1
    assert delta["unchanged_job_count"] == 1
    assert delta["change_fields"]["title"] == 1


def test_delta_multiple_field_changes(tmp_path: Path) -> None:
    current_ranked = tmp_path / "openai_ranked_jobs.cs.json"
    baseline_ranked = tmp_path / "baseline_ranked.json"

    baseline_jobs = [
        {"apply_url": "a", "title": "Alpha", "location": "NY", "team": "Core"},
    ]
    current_jobs = [
        {"apply_url": "a", "title": "Alpha v2", "location": "Remote", "team": "Core"},
    ]

    _write_json(current_ranked, current_jobs)
    _write_json(baseline_ranked, baseline_jobs)

    delta = compute_delta(
        None,
        current_ranked,
        None,
        baseline_ranked,
        "openai",
        "cs",
    )

    assert delta["changed_job_count"] == 1
    assert delta["change_fields"]["title"] == 1
    assert delta["change_fields"]["location"] == 1
