from __future__ import annotations

import random

from ji_engine.utils.diff_report import build_diff_markdown, build_diff_report, diff_report_digest


def test_diff_report_deterministic_ordering() -> None:
    prev = [
        {"provider": "openai", "job_id": "1", "title": "A", "apply_url": "https://a.example"},
        {"provider": "openai", "job_id": "2", "title": "B", "apply_url": "https://b.example"},
    ]
    curr = [
        {"provider": "openai", "job_id": "2", "title": "B", "apply_url": "https://b.example"},
        {"provider": "openai", "job_id": "3", "title": "C", "apply_url": "https://c.example"},
    ]
    report = build_diff_report(prev, curr, provider="openai", profile="cs", baseline_exists=True)
    report_again = build_diff_report(
        list(reversed(prev)), list(reversed(curr)), provider="openai", profile="cs", baseline_exists=True
    )

    assert report == report_again
    assert report["counts"]["added"] == 1
    assert report["counts"]["removed"] == 1
    assert report["counts"]["changed"] == 0
    assert [item["id"] for item in report["added"]]
    assert [item["id"] for item in report["removed"]]
    assert report["summary_hash"] == diff_report_digest(report)


def test_diff_report_stable_with_randomized_inputs() -> None:
    prev = [
        {"provider": "openai", "job_id": "1", "title": "A", "apply_url": "https://a.example"},
        {"provider": "openai", "job_id": "2", "title": "B", "apply_url": "https://b.example"},
        {"provider": "openai", "job_id": "3", "title": "C", "apply_url": "https://c.example"},
    ]
    curr = [
        {"provider": "openai", "job_id": "2", "title": "B", "apply_url": "https://b.example"},
        {"provider": "openai", "job_id": "3", "title": "C2", "apply_url": "https://c.example"},
        {"provider": "openai", "job_id": "4", "title": "D", "apply_url": "https://d.example"},
    ]
    rng = random.Random(0)
    rng.shuffle(prev)
    rng.shuffle(curr)

    report = build_diff_report(prev, curr, provider="openai", profile="cs", baseline_exists=True)
    report_again = build_diff_report(
        list(reversed(prev)), list(reversed(curr)), provider="openai", profile="cs", baseline_exists=True
    )

    assert report == report_again


def test_diff_markdown_includes_sections() -> None:
    report = {
        "provider": "openai",
        "profile": "cs",
        "baseline_exists": True,
        "counts": {"added": 1, "changed": 0, "removed": 0},
        "added": [{"id": "openai:1", "title": "A", "apply_url": "https://a"}],
        "changed": [],
        "removed": [],
    }
    md = build_diff_markdown(report)
    assert "# Diff since last run" in md
    assert "## Added" in md
    assert "## Changed" in md
    assert "## Removed" in md


def test_diff_report_uses_job_id_as_identity_key() -> None:
    prev = [
        {
            "provider": "openai",
            "job_id": "stable-id-1",
            "title": "Role A",
            "location": "Remote",
            "team": "CS",
            "level": "L4",
            "score": 80,
            "description_text": "same description",
        }
    ]
    curr = [
        {
            "provider": "openai",
            "job_id": "stable-id-1",
            "title": "Role A updated",
            "location": "Remote",
            "team": "CS",
            "level": "L4",
            "score": 82,
            "description_text": "same description",
        }
    ]
    report = build_diff_report(prev, curr, provider="openai", profile="cs", baseline_exists=True)
    assert report["counts"]["added"] == 0
    assert report["counts"]["removed"] == 0
    assert report["counts"]["changed"] == 1
    assert report["changed"][0]["id"] == "stable-id-1"
    assert "title" in report["changed"][0]["changed_fields"]
    assert "score" in report["changed"][0]["changed_fields"]


def test_diff_report_suppresses_ignored_ids() -> None:
    prev = [
        {"provider": "openai", "job_id": "job-a", "title": "Role A", "apply_url": "https://example.com/a"},
        {"provider": "openai", "job_id": "job-b", "title": "Role B", "apply_url": "https://example.com/b"},
    ]
    curr = [
        {"provider": "openai", "job_id": "job-a", "title": "Role A+", "apply_url": "https://example.com/a"},
        {"provider": "openai", "job_id": "job-c", "title": "Role C", "apply_url": "https://example.com/c"},
    ]
    report = build_diff_report(prev, curr, provider="openai", profile="cs", baseline_exists=True, ignored_ids={"job-a"})

    assert report["counts"] == {"added": 1, "changed": 0, "removed": 1}
    assert report["suppressed"]["ignored"] == 1
    assert [item["id"] for item in report["added"]] == ["job-c"]
    assert [item["id"] for item in report["removed"]] == ["job-b"]
    md = build_diff_markdown(report)
    assert "Suppressed by user_state(ignore): 1" in md
