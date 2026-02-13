from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

import scripts.score_jobs as score_jobs
from ji_engine.config import REPO_ROOT
from ji_engine.scoring import (
    ScoringConfigError,
    build_scoring_model_metadata,
    build_scoring_model_signature,
    load_scoring_config,
)


def _run_score_jobs(input_path: Path, profiles_path: Path, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    out_json = out_dir / "openai_ranked_jobs.cs.json"
    out_csv = out_dir / "openai_ranked_jobs.cs.csv"
    out_families = out_dir / "openai_ranked_families.cs.json"
    out_md = out_dir / "openai_shortlist.cs.md"
    out_top = out_dir / "openai_top.cs.md"

    argv = [
        "score_jobs.py",
        "--profile",
        "cs",
        "--profiles",
        str(profiles_path),
        "--in_path",
        str(input_path),
        "--scoring_config",
        str(REPO_ROOT / "config" / "scoring.v1.json"),
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
        "40",
    ]
    old_argv = sys.argv
    sys.argv = argv
    try:
        rc = score_jobs.main()
    finally:
        sys.argv = old_argv
    assert rc == 0
    return out_json


def test_scoring_config_fails_closed_when_invalid(tmp_path: Path) -> None:
    invalid_path = tmp_path / "scoring.invalid.json"
    invalid_path.write_text('{"schema_version": 1, "version": "v1", "algorithm_id": "x"}', encoding="utf-8")
    with pytest.raises(ScoringConfigError):
        load_scoring_config(invalid_path)


def test_score_jobs_exits_when_scoring_config_missing(tmp_path: Path) -> None:
    input_path = tmp_path / "in.json"
    input_path.write_text("[]", encoding="utf-8")
    profiles_path = tmp_path / "profiles.json"
    profiles_path.write_text(
        json.dumps(
            {
                "cs": {
                    "role_band_multipliers": {"CS_CORE": 1.25, "CS_ADJACENT": 1.15, "SOLUTIONS": 1.05, "OTHER": 0.95},
                    "profile_weights": {
                        "boost_cs_core": 15,
                        "boost_cs_adjacent": 5,
                        "boost_solutions": 2,
                        "penalty_research_heavy": -8,
                        "penalty_low_level": -5,
                        "penalty_strong_swe_only": -4,
                        "pin_manager_ai_deployment": 30,
                    },
                }
            }
        ),
        encoding="utf-8",
    )

    argv = [
        "score_jobs.py",
        "--profile",
        "cs",
        "--profiles",
        str(profiles_path),
        "--in_path",
        str(input_path),
        "--scoring_config",
        str(tmp_path / "missing.json"),
        "--out_json",
        str(tmp_path / "out.json"),
        "--out_csv",
        str(tmp_path / "out.csv"),
        "--out_families",
        str(tmp_path / "out_families.json"),
        "--out_md",
        str(tmp_path / "out.md"),
    ]
    old_argv = sys.argv
    sys.argv = argv
    try:
        with pytest.raises(SystemExit, match="Scoring config validation failed"):
            score_jobs.main()
    finally:
        sys.argv = old_argv


def test_scoring_replay_golden_output_matches_fixture(tmp_path: Path) -> None:
    fixture_dir = Path("tests/fixtures/scoring_v1")
    out_json = _run_score_jobs(
        fixture_dir / "input_jobs.json",
        fixture_dir / "profiles.json",
        tmp_path / "out",
    )
    expected = fixture_dir / "openai_ranked_jobs.cs.json"
    assert out_json.read_text(encoding="utf-8") == expected.read_text(encoding="utf-8")


def test_scoring_drift_signature_requires_intentional_update() -> None:
    config = load_scoring_config(REPO_ROOT / "config" / "scoring.v1.json")
    scoring_model = build_scoring_model_metadata(
        config=config,
        config_path=REPO_ROOT / "config" / "scoring.v1.json",
        profiles_path=REPO_ROOT / "config" / "profiles.json",
        scoring_inputs_by_provider={
            "openai": {
                "cs": {
                    "path": "state/runs/example/inputs/openai/cs/selected_scoring_input.json",
                    "sha256": "0" * 64,
                }
            }
        },
        repo_root=REPO_ROOT,
    )
    signature = build_scoring_model_signature(scoring_model)
    expected_signature = (Path("tests/fixtures/scoring_v1") / "signature.sha256").read_text(encoding="utf-8").strip()
    assert signature == expected_signature, (
        "Scoring model signature drifted while version is still v1. "
        "If scoring semantics changed intentionally, bump scoring model version and refresh fixture."
    )


def test_scoring_signature_is_path_stable_across_repo_root_forms() -> None:
    config = load_scoring_config(REPO_ROOT / "config" / "scoring.v1.json")
    scoring_inputs = {
        "openai": {
            "cs": {
                "path": "state/runs/example/inputs/openai/cs/selected_scoring_input.json",
                "sha256": "0" * 64,
            }
        }
    }
    abs_meta = build_scoring_model_metadata(
        config=config,
        config_path=REPO_ROOT / "config" / "scoring.v1.json",
        profiles_path=REPO_ROOT / "config" / "profiles.json",
        scoring_inputs_by_provider=scoring_inputs,
        repo_root=REPO_ROOT,
    )
    rel_meta = build_scoring_model_metadata(
        config=config,
        config_path=Path("config/scoring.v1.json"),
        profiles_path=Path("config/profiles.json"),
        scoring_inputs_by_provider=scoring_inputs,
        repo_root=REPO_ROOT,
    )
    assert build_scoring_model_signature(abs_meta) == build_scoring_model_signature(rel_meta)
