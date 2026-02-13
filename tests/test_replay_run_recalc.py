from __future__ import annotations

import json
import sys
from pathlib import Path

import scripts.replay_run as replay_run
from ji_engine.utils.verification import compute_sha256_file


def _run_score_jobs(
    input_path: Path,
    profiles_path: Path,
    profile: str,
    out_dir: Path,
    *,
    min_score: int = 40,
    us_only: bool = False,
) -> dict:
    import scripts.score_jobs as score_jobs

    out_dir.mkdir(parents=True, exist_ok=True)
    out_json = out_dir / f"openai_ranked_jobs.{profile}.json"
    out_csv = out_dir / f"openai_ranked_jobs.{profile}.csv"
    out_families = out_dir / f"openai_ranked_families.{profile}.json"
    out_md = out_dir / f"openai_shortlist.{profile}.md"
    out_top = out_dir / f"openai_top.{profile}.md"

    argv = [
        "score_jobs.py",
        "--profile",
        profile,
        "--profiles",
        str(profiles_path),
        "--in_path",
        str(input_path),
        "--out_json",
        str(out_json),
        "--out_csv",
        str(out_csv),
        "--out_families",
        str(out_families),
        "--out_md",
        str(out_md),
        "--out_md_top_n",
        str(out_top),
        "--min_score",
        str(min_score),
    ]
    if us_only:
        argv.append("--us_only")
    old_argv = sys.argv
    sys.argv = argv
    try:
        score_jobs.main()
    finally:
        sys.argv = old_argv

    return {
        "ranked_json": {"path": str(out_json), "sha256": compute_sha256_file(out_json)},
        "ranked_csv": {"path": str(out_csv), "sha256": compute_sha256_file(out_csv)},
        "ranked_families_json": {"path": str(out_families), "sha256": compute_sha256_file(out_families)},
        "shortlist_md": {"path": str(out_md), "sha256": compute_sha256_file(out_md)},
        "top_md": {"path": str(out_top), "sha256": compute_sha256_file(out_top)},
    }


def _write_profiles(path: Path) -> None:
    payload = {
        "cs": {
            "role_band_multipliers": {"CS_CORE": 1.1, "OTHER": 1.0},
            "profile_weights": {"boost_cs_core": 10, "penalty_low_level": -1},
        }
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_input(path: Path, job_id: str) -> None:
    payload = [
        {
            "job_id": job_id,
            "title": "Engineer",
            "location": "San Francisco, CA",
            "apply_url": f"https://example.com/{job_id}",
            "jd_text": "Build things.",
            "role_band": "CS_CORE",
        }
    ]
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_replay_recalc_passes(tmp_path: Path, monkeypatch) -> None:
    state_dir = tmp_path / "state"
    run_dir = state_dir / "runs" / "recalc-pass"
    archived_dir = run_dir / "inputs" / "openai" / "cs"
    archived_dir.mkdir(parents=True, exist_ok=True)

    input_path = archived_dir / "selected_scoring_input.json"
    profiles_path = archived_dir / "profiles.json"
    scoring_config_path = archived_dir / "scoring.v1.json"
    _write_input(input_path, "1")
    _write_profiles(profiles_path)
    scoring_config_path.write_text((Path("config/scoring.v1.json")).read_text(encoding="utf-8"), encoding="utf-8")

    expected_outputs = _run_score_jobs(input_path, profiles_path, "cs", run_dir / "expected")

    report = {
        "run_report_schema_version": 1,
        "run_id": "recalc-pass",
        "providers": ["openai"],
        "flags": {"min_score": 40, "us_only": False},
        "archived_inputs_by_provider_profile": {
            "openai": {
                "cs": {
                    "selected_scoring_input": {
                        "source_path": str(input_path),
                        "archived_path": input_path.relative_to(state_dir).as_posix(),
                        "sha256": compute_sha256_file(input_path),
                        "bytes": input_path.stat().st_size,
                        "hash_algo": "sha256",
                    },
                    "profile_config": {
                        "source_path": str(profiles_path),
                        "archived_path": profiles_path.relative_to(state_dir).as_posix(),
                        "sha256": compute_sha256_file(profiles_path),
                        "bytes": profiles_path.stat().st_size,
                        "hash_algo": "sha256",
                    },
                    "scoring_config": {
                        "source_path": str(scoring_config_path),
                        "archived_path": scoring_config_path.relative_to(state_dir).as_posix(),
                        "sha256": compute_sha256_file(scoring_config_path),
                        "bytes": scoring_config_path.stat().st_size,
                        "hash_algo": "sha256",
                    },
                }
            }
        },
        "outputs_by_profile": {"cs": expected_outputs},
        "selection": {
            "scrape_provenance": {},
            "classified_job_count": 0,
            "classified_job_count_by_provider": {"openai": 0},
        },
    }
    report_path = run_dir / "run_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report), encoding="utf-8")

    monkeypatch.setattr(replay_run, "STATE_DIR", state_dir)
    monkeypatch.setattr(replay_run, "RUN_METADATA_DIR", state_dir / "runs")

    rc = replay_run.main(["--run-dir", str(run_dir), "--profile", "cs", "--strict", "--recalc"])
    assert rc == 0


def test_replay_recalc_detects_mismatch(tmp_path: Path, monkeypatch) -> None:
    state_dir = tmp_path / "state"
    run_dir = state_dir / "runs" / "recalc-mismatch"
    archived_dir = run_dir / "inputs" / "openai" / "cs"
    archived_dir.mkdir(parents=True, exist_ok=True)

    input_path = archived_dir / "selected_scoring_input.json"
    profiles_path = archived_dir / "profiles.json"
    scoring_config_path = archived_dir / "scoring.v1.json"
    _write_input(input_path, "1")
    _write_profiles(profiles_path)
    scoring_config_path.write_text((Path("config/scoring.v1.json")).read_text(encoding="utf-8"), encoding="utf-8")

    expected_outputs = _run_score_jobs(input_path, profiles_path, "cs", run_dir / "expected")

    report = {
        "run_report_schema_version": 1,
        "run_id": "recalc-mismatch",
        "providers": ["openai"],
        "flags": {"min_score": 40, "us_only": False},
        "archived_inputs_by_provider_profile": {
            "openai": {
                "cs": {
                    "selected_scoring_input": {
                        "source_path": str(input_path),
                        "archived_path": input_path.relative_to(state_dir).as_posix(),
                        "sha256": compute_sha256_file(input_path),
                        "bytes": input_path.stat().st_size,
                        "hash_algo": "sha256",
                    },
                    "profile_config": {
                        "source_path": str(profiles_path),
                        "archived_path": profiles_path.relative_to(state_dir).as_posix(),
                        "sha256": compute_sha256_file(profiles_path),
                        "bytes": profiles_path.stat().st_size,
                        "hash_algo": "sha256",
                    },
                    "scoring_config": {
                        "source_path": str(scoring_config_path),
                        "archived_path": scoring_config_path.relative_to(state_dir).as_posix(),
                        "sha256": compute_sha256_file(scoring_config_path),
                        "bytes": scoring_config_path.stat().st_size,
                        "hash_algo": "sha256",
                    },
                }
            }
        },
        "outputs_by_profile": {"cs": expected_outputs},
        "selection": {
            "scrape_provenance": {},
            "classified_job_count": 0,
            "classified_job_count_by_provider": {"openai": 0},
        },
    }
    report_path = run_dir / "run_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report), encoding="utf-8")

    # Corrupt archived input so regenerated output hash mismatches expected.
    _write_input(input_path, "2")

    monkeypatch.setattr(replay_run, "STATE_DIR", state_dir)
    monkeypatch.setattr(replay_run, "RUN_METADATA_DIR", state_dir / "runs")

    rc = replay_run.main(["--run-dir", str(run_dir), "--profile", "cs", "--strict", "--recalc"])
    assert rc == 2
