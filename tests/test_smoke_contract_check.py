from pathlib import Path

import pytest

from scripts import smoke_contract_check


def _write_json(path: Path, data) -> None:
    path.write_text(__import__("json").dumps(data), encoding="utf-8")


def _write_csv(path: Path, rows) -> None:
    import csv

    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerows(rows)


def test_smoke_contract_check_ok(tmp_path: Path) -> None:
    artifacts = tmp_path / "smoke_artifacts"
    artifacts.mkdir()

    labeled = [{"id": 1}, {"id": 2}, {"id": 3}]
    ranked = [{"id": 1}, {"id": 2}, {"id": 3}, {"id": 4}, {"id": 5}]
    _write_json(artifacts / "openai_labeled_jobs.json", labeled)
    _write_json(artifacts / "openai_ranked_jobs.cs.json", ranked)
    _write_csv(artifacts / "openai_ranked_jobs.cs.csv", [["id"], [1], [2], [3], [4], [5]])
    _write_json(
        artifacts / "run_report.json",
        {
            "providers": ["openai"],
            "run_report_schema_version": 1,
            "config_fingerprint": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "environment_fingerprint": {
                "python_version": "3.10.14",
                "platform": "test",
                "image_tag": None,
                "git_sha": None,
            },
            "verifiable_artifacts": {},
            "run_id": "run-1",
            "selection": {
                "scrape_provenance": {"openai": {"scrape_mode": "snapshot"}},
                "classified_job_count_by_provider": {"openai": len(labeled)},
                "classified_job_count": len(labeled),
            },
            "delta_summary": {
                "baseline_run_id": None,
                "baseline_run_path": None,
                "current_run_id": "run-1",
                "provider_profile": {
                    "openai": {
                        "cs": {
                            "provider": "openai",
                            "profile": "cs",
                            "labeled_total": len(labeled),
                            "ranked_total": len(ranked),
                            "new_job_count": 0,
                            "removed_job_count": 0,
                            "changed_job_count": 0,
                            "unchanged_job_count": 0,
                            "new_job_ids": [],
                            "removed_job_ids": [],
                            "changed_job_ids": [],
                            "change_fields": {"title": 0, "location": 0, "team": 0, "url": 0},
                            "baseline_run_id": None,
                            "baseline_run_path": None,
                            "current_run_id": "run-1",
                        }
                    }
                },
            },
        },
    )

    assert smoke_contract_check.main([str(artifacts), "--min-ranked", "5"]) == 0


def test_smoke_contract_check_missing_file(tmp_path: Path) -> None:
    artifacts = tmp_path / "smoke_artifacts"
    artifacts.mkdir()
    _write_json(artifacts / "openai_labeled_jobs.json", [{"id": 1}])
    _write_json(artifacts / "openai_ranked_jobs.cs.json", [{"id": 1}])
    _write_csv(artifacts / "openai_ranked_jobs.cs.csv", [["id"], [1]])
    _write_json(
        artifacts / "run_report.json",
        {
            "providers": ["openai"],
            "run_report_schema_version": 1,
            "config_fingerprint": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "environment_fingerprint": {
                "python_version": "3.10.14",
                "platform": "test",
                "image_tag": None,
                "git_sha": None,
            },
            "verifiable_artifacts": {},
            "run_id": "run-1",
            "selection": {
                "scrape_provenance": {"openai": {"scrape_mode": "snapshot"}},
                "classified_job_count_by_provider": {"openai": 1},
                "classified_job_count": 1,
            },
            "delta_summary": {
                "baseline_run_id": "run-0",
                "baseline_run_path": "/tmp/run-0.json",
                "current_run_id": "run-1",
                "provider_profile": {
                    "openai": {
                        "cs": {
                            "provider": "openai",
                            "profile": "cs",
                            "labeled_total": 1,
                            "ranked_total": 1,
                            "new_job_count": 1,
                            "removed_job_count": 0,
                            "changed_job_count": 0,
                            "unchanged_job_count": 0,
                            "new_job_ids": [],
                            "removed_job_ids": [],
                            "changed_job_ids": [],
                            "change_fields": {"title": 0, "location": 0, "team": 0, "url": 0},
                            "baseline_run_id": "run-0",
                            "baseline_run_path": "/tmp/run-0.json",
                            "current_run_id": "run-1",
                        }
                    }
                },
            },
        },
    )

    (artifacts / "openai_ranked_jobs.cs.csv").unlink()

    with pytest.raises(RuntimeError):
        smoke_contract_check.main([str(artifacts)])


def test_smoke_contract_check_missing_classified_count(tmp_path: Path) -> None:
    artifacts = tmp_path / "smoke_artifacts"
    artifacts.mkdir()

    labeled = [{"id": 1}]
    ranked = [{"id": 1}, {"id": 2}, {"id": 3}, {"id": 4}, {"id": 5}]
    _write_json(artifacts / "openai_labeled_jobs.json", labeled)
    _write_json(artifacts / "openai_ranked_jobs.cs.json", ranked)
    _write_csv(artifacts / "openai_ranked_jobs.cs.csv", [["id"], [1], [2], [3], [4], [5]])
    _write_json(
        artifacts / "run_report.json",
        {
            "providers": ["openai"],
            "run_report_schema_version": 1,
            "config_fingerprint": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "environment_fingerprint": {
                "python_version": "3.10.14",
                "platform": "test",
                "image_tag": None,
                "git_sha": None,
            },
            "verifiable_artifacts": {},
            "run_id": "run-1",
            "selection": {
                "scrape_provenance": {"openai": {"scrape_mode": "snapshot"}},
                "classified_job_count": len(labeled),
            },
        },
    )

    with pytest.raises(RuntimeError, match="classified_job_count_by_provider"):
        smoke_contract_check.main([str(artifacts)])


def test_smoke_contract_check_missing_delta_summary(tmp_path: Path) -> None:
    artifacts = tmp_path / "smoke_artifacts"
    artifacts.mkdir()

    labeled = [{"id": 1}]
    ranked = [{"id": 1}, {"id": 2}, {"id": 3}, {"id": 4}, {"id": 5}]
    _write_json(artifacts / "openai_labeled_jobs.json", labeled)
    _write_json(artifacts / "openai_ranked_jobs.cs.json", ranked)
    _write_csv(artifacts / "openai_ranked_jobs.cs.csv", [["id"], [1], [2], [3], [4], [5]])
    _write_json(
        artifacts / "run_report.json",
        {
            "providers": ["openai"],
            "run_report_schema_version": 1,
            "config_fingerprint": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "environment_fingerprint": {
                "python_version": "3.10.14",
                "platform": "test",
                "image_tag": None,
                "git_sha": None,
            },
            "verifiable_artifacts": {},
            "run_id": "run-1",
            "selection": {
                "scrape_provenance": {"openai": {"scrape_mode": "snapshot"}},
                "classified_job_count_by_provider": {"openai": len(labeled)},
                "classified_job_count": len(labeled),
            },
        },
    )

    with pytest.raises(RuntimeError, match="missing delta_summary"):
        smoke_contract_check.main([str(artifacts)])


def test_smoke_contract_check_missing_schema_version(tmp_path: Path) -> None:
    artifacts = tmp_path / "smoke_artifacts"
    artifacts.mkdir()

    labeled = [{"id": 1}]
    ranked = [{"id": 1}, {"id": 2}, {"id": 3}, {"id": 4}, {"id": 5}]
    _write_json(artifacts / "openai_labeled_jobs.json", labeled)
    _write_json(artifacts / "openai_ranked_jobs.cs.json", ranked)
    _write_csv(artifacts / "openai_ranked_jobs.cs.csv", [["id"], [1], [2], [3], [4], [5]])
    _write_json(
        artifacts / "run_report.json",
        {
            "providers": ["openai"],
            "run_id": "run-1",
            "selection": {
                "scrape_provenance": {"openai": {"scrape_mode": "snapshot"}},
                "classified_job_count_by_provider": {"openai": len(labeled)},
                "classified_job_count": len(labeled),
            },
            "delta_summary": {
                "baseline_run_id": None,
                "baseline_run_path": None,
                "current_run_id": "run-1",
                "provider_profile": {"openai": {"cs": {"labeled_total": len(labeled), "ranked_total": len(ranked)}}},
            },
        },
    )

    with pytest.raises(RuntimeError, match="missing run_report_schema_version"):
        smoke_contract_check.main([str(artifacts)])


def test_smoke_contract_check_wrong_schema_version(tmp_path: Path) -> None:
    artifacts = tmp_path / "smoke_artifacts"
    artifacts.mkdir()

    labeled = [{"id": 1}]
    ranked = [{"id": 1}, {"id": 2}, {"id": 3}, {"id": 4}, {"id": 5}]
    _write_json(artifacts / "openai_labeled_jobs.json", labeled)
    _write_json(artifacts / "openai_ranked_jobs.cs.json", ranked)
    _write_csv(artifacts / "openai_ranked_jobs.cs.csv", [["id"], [1], [2], [3], [4], [5]])
    _write_json(
        artifacts / "run_report.json",
        {
            "providers": ["openai"],
            "run_report_schema_version": 0,
            "run_id": "run-1",
            "selection": {
                "scrape_provenance": {"openai": {"scrape_mode": "snapshot"}},
                "classified_job_count_by_provider": {"openai": len(labeled)},
                "classified_job_count": len(labeled),
            },
            "delta_summary": {
                "baseline_run_id": None,
                "baseline_run_path": None,
                "current_run_id": "run-1",
                "provider_profile": {"openai": {"cs": {"labeled_total": len(labeled), "ranked_total": len(ranked)}}},
            },
        },
    )

    with pytest.raises(RuntimeError, match="run_report_schema_version 0 < smoke_contract_version"):
        smoke_contract_check.main([str(artifacts)])


def test_smoke_contract_check_min_schema_version(tmp_path: Path) -> None:
    artifacts = tmp_path / "smoke_artifacts"
    artifacts.mkdir()

    labeled = [{"id": 1}]
    ranked = [{"id": 1}, {"id": 2}, {"id": 3}, {"id": 4}, {"id": 5}]
    _write_json(artifacts / "openai_labeled_jobs.json", labeled)
    _write_json(artifacts / "openai_ranked_jobs.cs.json", ranked)
    _write_csv(artifacts / "openai_ranked_jobs.cs.csv", [["id"], [1], [2], [3], [4], [5]])
    _write_json(
        artifacts / "run_report.json",
        {
            "providers": ["openai"],
            "run_report_schema_version": 1,
            "config_fingerprint": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "environment_fingerprint": {
                "python_version": "3.10.14",
                "platform": "test",
                "image_tag": None,
                "git_sha": None,
            },
            "verifiable_artifacts": {},
            "run_id": "run-1",
            "selection": {
                "scrape_provenance": {"openai": {"scrape_mode": "snapshot"}},
                "classified_job_count_by_provider": {"openai": len(labeled)},
                "classified_job_count": len(labeled),
            },
            "delta_summary": {
                "baseline_run_id": None,
                "baseline_run_path": None,
                "current_run_id": "run-1",
                "provider_profile": {
                    "openai": {
                        "cs": {
                            "provider": "openai",
                            "profile": "cs",
                            "labeled_total": len(labeled),
                            "ranked_total": len(ranked),
                            "new_job_count": 0,
                            "removed_job_count": 0,
                            "changed_job_count": 0,
                            "unchanged_job_count": 0,
                            "new_job_ids": [],
                            "removed_job_ids": [],
                            "changed_job_ids": [],
                            "change_fields": {"title": 0, "location": 0, "team": 0, "url": 0},
                            "baseline_run_id": None,
                            "baseline_run_path": None,
                            "current_run_id": "run-1",
                        }
                    }
                },
            },
        },
    )

    assert (
        smoke_contract_check.main([str(artifacts), "--require-schema-version", "0", "--min-schema-version", "1"]) == 0
    )


def test_smoke_contract_check_alerts_validation(tmp_path: Path) -> None:
    artifacts = tmp_path / "smoke_artifacts"
    artifacts.mkdir()

    labeled = [{"id": 1}, {"id": 2}]
    ranked = [
        {"id": 1, "title": "Alpha", "apply_url": "https://example.com/a", "score": 90},
        {"id": 2, "title": "Beta", "apply_url": "https://example.com/b", "score": 80},
        {"id": 3, "title": "Gamma", "apply_url": "https://example.com/c", "score": 70},
        {"id": 4, "title": "Delta", "apply_url": "https://example.com/d", "score": 60},
        {"id": 5, "title": "Epsilon", "apply_url": "https://example.com/e", "score": 50},
    ]
    _write_json(artifacts / "openai_labeled_jobs.json", labeled)
    _write_json(artifacts / "openai_ranked_jobs.cs.json", ranked)
    _write_csv(artifacts / "openai_ranked_jobs.cs.csv", [["id"], [1], [2], [3], [4], [5]])
    _write_json(
        artifacts / "openai_alerts.cs.json",
        {
            "counts": {"new": 1, "removed": 0, "score_changes": 0, "title_or_location_changes": 0},
            "new_jobs": [
                {
                    "job_id": "https://example.com/a",
                    "title": "Alpha",
                    "score": 90,
                    "url": "https://example.com/a",
                }
            ],
            "removed_jobs": [],
            "score_changes": [],
            "title_or_location_changes": [],
        },
    )
    _write_json(
        artifacts / "run_report.json",
        {
            "providers": ["openai"],
            "run_report_schema_version": 1,
            "config_fingerprint": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "environment_fingerprint": {
                "python_version": "3.10.14",
                "platform": "test",
                "image_tag": None,
                "git_sha": None,
            },
            "verifiable_artifacts": {},
            "run_id": "run-1",
            "selection": {
                "scrape_provenance": {"openai": {"scrape_mode": "snapshot"}},
                "classified_job_count_by_provider": {"openai": len(labeled)},
                "classified_job_count": len(labeled),
            },
            "delta_summary": {
                "baseline_run_id": None,
                "baseline_run_path": None,
                "current_run_id": "run-1",
                "provider_profile": {
                    "openai": {
                        "cs": {
                            "provider": "openai",
                            "profile": "cs",
                            "labeled_total": len(labeled),
                            "ranked_total": len(ranked),
                            "new_job_count": 0,
                            "removed_job_count": 0,
                            "changed_job_count": 0,
                            "unchanged_job_count": 0,
                            "new_job_ids": [],
                            "removed_job_ids": [],
                            "changed_job_ids": [],
                            "change_fields": {"title": 0, "location": 0, "team": 0, "url": 0},
                            "baseline_run_id": None,
                            "baseline_run_path": None,
                            "current_run_id": "run-1",
                        }
                    }
                },
            },
        },
    )

    assert smoke_contract_check.main([str(artifacts)]) == 0


def test_smoke_contract_check_alerts_count_mismatch(tmp_path: Path) -> None:
    artifacts = tmp_path / "smoke_artifacts"
    artifacts.mkdir()

    labeled = [{"id": 1}]
    ranked = [
        {"id": 1, "title": "Alpha", "apply_url": "https://example.com/a", "score": 90},
        {"id": 2, "title": "Beta", "apply_url": "https://example.com/b", "score": 80},
        {"id": 3, "title": "Gamma", "apply_url": "https://example.com/c", "score": 70},
        {"id": 4, "title": "Delta", "apply_url": "https://example.com/d", "score": 60},
        {"id": 5, "title": "Epsilon", "apply_url": "https://example.com/e", "score": 50},
    ]
    _write_json(artifacts / "openai_labeled_jobs.json", labeled)
    _write_json(artifacts / "openai_ranked_jobs.cs.json", ranked)
    _write_csv(artifacts / "openai_ranked_jobs.cs.csv", [["id"], [1], [2], [3], [4], [5]])
    _write_json(
        artifacts / "openai_alerts.cs.json",
        {
            "counts": {"new": 0, "removed": 0, "score_changes": 0, "title_or_location_changes": 0},
            "new_jobs": [{"job_id": "https://example.com/a", "title": "Alpha"}],
            "removed_jobs": [],
            "score_changes": [],
            "title_or_location_changes": [],
        },
    )
    _write_json(
        artifacts / "run_report.json",
        {
            "providers": ["openai"],
            "run_report_schema_version": 1,
            "config_fingerprint": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "environment_fingerprint": {
                "python_version": "3.10.14",
                "platform": "test",
                "image_tag": None,
                "git_sha": None,
            },
            "verifiable_artifacts": {},
            "run_id": "run-1",
            "selection": {
                "scrape_provenance": {"openai": {"scrape_mode": "snapshot"}},
                "classified_job_count_by_provider": {"openai": len(labeled)},
                "classified_job_count": len(labeled),
            },
            "delta_summary": {
                "baseline_run_id": None,
                "baseline_run_path": None,
                "current_run_id": "run-1",
                "provider_profile": {
                    "openai": {
                        "cs": {
                            "provider": "openai",
                            "profile": "cs",
                            "labeled_total": len(labeled),
                            "ranked_total": len(ranked),
                            "new_job_count": 0,
                            "removed_job_count": 0,
                            "changed_job_count": 0,
                            "unchanged_job_count": 0,
                            "new_job_ids": [],
                            "removed_job_ids": [],
                            "changed_job_ids": [],
                            "change_fields": {"title": 0, "location": 0, "team": 0, "url": 0},
                            "baseline_run_id": None,
                            "baseline_run_path": None,
                            "current_run_id": "run-1",
                        }
                    }
                },
            },
        },
    )

    with pytest.raises(RuntimeError, match="counts.new"):
        smoke_contract_check.main([str(artifacts)])


def test_smoke_contract_check_classified_total_mismatch(tmp_path: Path) -> None:
    artifacts = tmp_path / "smoke_artifacts"
    artifacts.mkdir()

    labeled = [{"id": 1}, {"id": 2}]
    ranked = [{"id": 1}, {"id": 2}, {"id": 3}, {"id": 4}, {"id": 5}]
    _write_json(artifacts / "openai_labeled_jobs.json", labeled)
    _write_json(artifacts / "openai_ranked_jobs.cs.json", ranked)
    _write_csv(artifacts / "openai_ranked_jobs.cs.csv", [["id"], [1], [2], [3], [4], [5]])
    _write_json(
        artifacts / "run_report.json",
        {
            "providers": ["openai"],
            "run_report_schema_version": 1,
            "config_fingerprint": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "environment_fingerprint": {
                "python_version": "3.10.14",
                "platform": "test",
                "image_tag": None,
                "git_sha": None,
            },
            "verifiable_artifacts": {},
            "run_id": "run-1",
            "selection": {
                "scrape_provenance": {"openai": {"scrape_mode": "snapshot"}},
                "classified_job_count_by_provider": {"openai": len(labeled)},
                "classified_job_count": len(labeled) + 1,
            },
            "delta_summary": {
                "baseline_run_id": None,
                "baseline_run_path": None,
                "current_run_id": "run-1",
                "provider_profile": {
                    "openai": {
                        "cs": {
                            "provider": "openai",
                            "profile": "cs",
                            "labeled_total": len(labeled),
                            "ranked_total": len(ranked),
                            "new_job_count": 0,
                            "removed_job_count": 0,
                            "changed_job_count": 0,
                            "unchanged_job_count": 0,
                            "new_job_ids": [],
                            "removed_job_ids": [],
                            "changed_job_ids": [],
                            "change_fields": {"title": 0, "location": 0, "team": 0, "url": 0},
                            "baseline_run_id": None,
                            "baseline_run_path": None,
                            "current_run_id": "run-1",
                        }
                    }
                },
            },
        },
    )

    with pytest.raises(RuntimeError, match="classified_job_count mismatch"):
        smoke_contract_check.main([str(artifacts)])


def test_smoke_contract_check_ranked_total_csv_mismatch(tmp_path: Path) -> None:
    artifacts = tmp_path / "smoke_artifacts"
    artifacts.mkdir()

    labeled = [{"id": 1}, {"id": 2}]
    ranked = [{"id": 1}, {"id": 2}, {"id": 3}, {"id": 4}, {"id": 5}]
    _write_json(artifacts / "openai_labeled_jobs.json", labeled)
    _write_json(artifacts / "openai_ranked_jobs.cs.json", ranked)
    _write_csv(artifacts / "openai_ranked_jobs.cs.csv", [["id"], [1], [2], [3], [4]])
    _write_json(
        artifacts / "run_report.json",
        {
            "providers": ["openai"],
            "run_report_schema_version": 1,
            "config_fingerprint": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "environment_fingerprint": {
                "python_version": "3.10.14",
                "platform": "test",
                "image_tag": None,
                "git_sha": None,
            },
            "verifiable_artifacts": {},
            "run_id": "run-1",
            "selection": {
                "scrape_provenance": {"openai": {"scrape_mode": "snapshot"}},
                "classified_job_count_by_provider": {"openai": len(labeled)},
                "classified_job_count": len(labeled),
            },
            "delta_summary": {
                "baseline_run_id": None,
                "baseline_run_path": None,
                "current_run_id": "run-1",
                "provider_profile": {
                    "openai": {
                        "cs": {
                            "provider": "openai",
                            "profile": "cs",
                            "labeled_total": len(labeled),
                            "ranked_total": len(ranked),
                            "new_job_count": 0,
                            "removed_job_count": 0,
                            "changed_job_count": 0,
                            "unchanged_job_count": 0,
                            "new_job_ids": [],
                            "removed_job_ids": [],
                            "changed_job_ids": [],
                            "change_fields": {"title": 0, "location": 0, "team": 0, "url": 0},
                            "baseline_run_id": None,
                            "baseline_run_path": None,
                            "current_run_id": "run-1",
                        }
                    }
                },
            },
        },
    )

    with pytest.raises(RuntimeError, match="rows"):
        smoke_contract_check.main([str(artifacts)])
