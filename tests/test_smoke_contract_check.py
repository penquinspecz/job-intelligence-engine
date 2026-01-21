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
            "selection": {
                "scrape_provenance": {"openai": {"scrape_mode": "snapshot"}},
                "classified_job_count_by_provider": {"openai": len(labeled)},
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
            "selection": {
                "scrape_provenance": {"openai": {"scrape_mode": "snapshot"}},
                "classified_job_count_by_provider": {"openai": 1},
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
            "selection": {"scrape_provenance": {"openai": {"scrape_mode": "snapshot"}}},
        },
    )

    with pytest.raises(RuntimeError, match="missing classified_job_count_by_provider"):
        smoke_contract_check.main([str(artifacts)])
