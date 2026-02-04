from __future__ import annotations

import hashlib
import json
from pathlib import Path

import scripts.replay_run as replay_run


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write(path: Path, data: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return _sha256_bytes(data)


def test_replay_run_passes_with_matching_hashes(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    scoring_path = run_dir / "inputs" / "openai_enriched_jobs.json"
    ranked_path = run_dir / "openai_ranked_jobs.cs.json"

    scoring_sha = _write(scoring_path, b"[]")
    ranked_sha = _write(ranked_path, b"[1]")

    report = {
        "run_report_schema_version": 1,
        "run_id": "2026-01-01T00:00:00Z",
        "selection": {
            "scrape_provenance": {},
            "classified_job_count": 0,
            "classified_job_count_by_provider": {"openai": 0},
        },
        "scoring_inputs_by_profile": {"cs": {"path": str(scoring_path), "sha256": scoring_sha}},
        "outputs_by_profile": {"cs": {"ranked_json": {"path": str(ranked_path), "sha256": ranked_sha}}},
    }

    report_path = run_dir / "run_report.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")

    exit_code, lines, _artifacts, _counts = replay_run._replay_report(
        report, "cs", strict=True, state_dir=replay_run.STATE_DIR
    )
    assert exit_code == 0
    assert any(line.startswith("PASS:") for line in lines)


def test_replay_run_detects_mismatch(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    scoring_path = run_dir / "inputs" / "openai_enriched_jobs.json"
    ranked_path = run_dir / "openai_ranked_jobs.cs.json"

    scoring_sha = _write(scoring_path, b"[]")
    ranked_sha = _write(ranked_path, b"[1]")

    report = {
        "run_report_schema_version": 1,
        "run_id": "2026-01-01T00:00:00Z",
        "selection": {
            "scrape_provenance": {},
            "classified_job_count": 0,
            "classified_job_count_by_provider": {"openai": 0},
        },
        "scoring_inputs_by_profile": {"cs": {"path": str(scoring_path), "sha256": scoring_sha}},
        "outputs_by_profile": {"cs": {"ranked_json": {"path": str(ranked_path), "sha256": ranked_sha}}},
    }

    report_path = run_dir / "run_report.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")

    # Corrupt ranked output after report was written.
    ranked_path.write_bytes(b"[2]")

    exit_code, lines, artifacts, _counts = replay_run._replay_report(
        report, "cs", strict=True, state_dir=replay_run.STATE_DIR
    )
    assert exit_code == 2
    assert any(line.startswith("FAIL:") for line in lines)
    assert any("mismatched" in line.lower() for line in lines)
    assert artifacts
    assert artifacts["output:ranked_json"]["path"].endswith("openai_ranked_jobs.cs.json")
