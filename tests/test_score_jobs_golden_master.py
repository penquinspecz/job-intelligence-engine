from __future__ import annotations

import csv
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from ji_engine.utils.job_identity import job_identity
from scripts.score_jobs import _serialize_json, build_families


def run_score_jobs(tmp_path: Path, *, run_name: str = "run") -> tuple[list[dict], list[str], Path, Path]:
    repo_root = Path(__file__).resolve().parents[1]
    fixture = repo_root / "tests" / "fixtures" / "openai_enriched_jobs.sample.json"

    out_dir = tmp_path / run_name
    out_dir.mkdir(parents=True, exist_ok=True)
    out_json = out_dir / "ranked.json"
    out_csv = out_dir / "ranked.csv"
    out_families = out_dir / "families.json"
    out_md = out_dir / "shortlist.md"

    cmd = [
        sys.executable,
        "scripts/score_jobs.py",
        "--profile",
        "cs",
        "--in_path",
        str(fixture),
        "--out_json",
        str(out_json),
        "--out_csv",
        str(out_csv),
        "--out_families",
        str(out_families),
        "--out_md",
        str(out_md),
    ]

    subprocess.run(cmd, cwd=repo_root, check=True)
    ranked = json.loads(out_json.read_text(encoding="utf-8"))
    with out_csv.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        headers = list(reader.fieldnames or [])
    return ranked, headers, out_json, out_families


def test_score_jobs_golden_master(tmp_path: Path) -> None:
    ranked, headers, _, _ = run_score_jobs(tmp_path)

    assert len(ranked) == 20  # fixture count

    titles = [j["title"] for j in ranked[:10]]
    scores = [j.get("score") for j in ranked[:10]]
    heuristic_scores = [j.get("heuristic_score") for j in ranked[:10]]
    final_scores = [j.get("final_score") for j in ranked[:10]]

    expected_titles = [
        "Manager, AI Deployment - AMER",
        "Partner Solutions Architect",
        "Solution Architect Manager, Digital Natives",
        "Forward Deployed Software Engineer - SF",
        "Forward Deployed Software Engineer - Munich",
        "Forward Deployed Software Engineer - NYC",
        "Forward Deployed Engineer - Life Sciences - SF",
        "Forward Deployed Engineer - Life Sciences - NYC",
        "Forward Deployed Engineer, Gov",
        "Forward Deployed Engineer - Munich",
    ]

    expected_scores = [100, 100, 97, 96, 96, 96, 84, 84, 84, 83]
    expected_heuristic_scores = [127, 116, 97, 96, 96, 96, 84, 84, 84, 83]

    assert titles == expected_titles
    assert scores == expected_scores
    assert heuristic_scores == expected_heuristic_scores  # no AI payload in fixture
    assert final_scores == expected_scores

    # Verify stable sort: for tied scores, job_identity is non-decreasing
    for i in range(len(ranked) - 1):
        curr_score = ranked[i].get("score", 0)
        next_score = ranked[i + 1].get("score", 0)
        if curr_score == next_score:
            curr_id = job_identity(ranked[i])
            next_id = job_identity(ranked[i + 1])
            assert curr_id <= next_id, f"Tied scores at index {i}, {i + 1} not ordered by job_identity"

    # Explanations exist and are well-formed; should not affect ordering/scores.
    assert "explanation_summary" in headers
    assert "content_fingerprint" in ranked[0]
    for j in ranked[:5]:
        expl = j.get("explanation")
        assert isinstance(expl, dict)
        assert expl.get("heuristic_score") == j.get("heuristic_score")
        assert "heuristic_reasons_top3" in expl
        assert "match_score" in expl
        assert "match_rationale" in expl
        assert expl.get("final_score") == j.get("final_score")
        assert "blend_weight_used" in expl
        assert "ai_blend_config" in expl
        cfg = expl.get("ai_blend_config") or {}
        assert cfg.get("weight_used") == expl.get("blend_weight_used")
        assert "missing_required_skills" in expl


def test_score_jobs_deterministic_hash(tmp_path: Path) -> None:
    _, _, first_json, _ = run_score_jobs(tmp_path, run_name="reference")
    _, _, second_json, _ = run_score_jobs(tmp_path, run_name="repeat")
    hash1 = hashlib.sha256(first_json.read_bytes()).hexdigest()
    hash2 = hashlib.sha256(second_json.read_bytes()).hexdigest()
    assert hash1 == hash2, "Ranking JSON should be deterministic across identical runs"


def test_ranked_json_serialization_stable(tmp_path: Path) -> None:
    _, _, ranked_json, _ = run_score_jobs(tmp_path, run_name="parser")
    original_text = ranked_json.read_text(encoding="utf-8")
    data = json.loads(original_text)
    assert _serialize_json(data) == original_text


def test_build_families_empty_input():
    assert build_families([]) == []


def test_families_json_deterministic(tmp_path: Path) -> None:
    _, _, _, first_families = run_score_jobs(tmp_path, run_name="families_ref")
    _, _, _, second_families = run_score_jobs(tmp_path, run_name="families_repeat")
    hash1 = hashlib.sha256(first_families.read_bytes()).hexdigest()
    hash2 = hashlib.sha256(second_families.read_bytes()).hexdigest()
    assert hash1 == hash2, "Families JSON should be deterministic across identical runs"


def test_score_jobs_semantic_disabled_matches_baseline(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    fixture = repo_root / "tests" / "fixtures" / "openai_enriched_jobs.sample.json"

    baseline_dir = tmp_path / "baseline"
    baseline_dir.mkdir(parents=True, exist_ok=True)
    baseline_json = baseline_dir / "ranked.json"

    disabled_dir = tmp_path / "disabled"
    disabled_dir.mkdir(parents=True, exist_ok=True)
    disabled_json = disabled_dir / "ranked.json"
    semantic_out = disabled_dir / "semantic_scores.json"

    base_cmd = [
        sys.executable,
        "scripts/score_jobs.py",
        "--profile",
        "cs",
        "--in_path",
        str(fixture),
        "--out_json",
        str(baseline_json),
        "--out_csv",
        str(baseline_dir / "ranked.csv"),
        "--out_families",
        str(baseline_dir / "families.json"),
        "--out_md",
        str(baseline_dir / "shortlist.md"),
    ]
    subprocess.run(base_cmd, cwd=repo_root, check=True)

    disabled_cmd = [
        sys.executable,
        "scripts/score_jobs.py",
        "--profile",
        "cs",
        "--in_path",
        str(fixture),
        "--out_json",
        str(disabled_json),
        "--out_csv",
        str(disabled_dir / "ranked.csv"),
        "--out_families",
        str(disabled_dir / "families.json"),
        "--out_md",
        str(disabled_dir / "shortlist.md"),
        "--semantic_scores_out",
        str(semantic_out),
    ]
    env = dict(os.environ)
    env["SEMANTIC_ENABLED"] = "0"
    subprocess.run(disabled_cmd, cwd=repo_root, check=True, env=env)

    assert baseline_json.read_text(encoding="utf-8") == disabled_json.read_text(encoding="utf-8")
    evidence = json.loads(semantic_out.read_text(encoding="utf-8"))
    assert evidence["enabled"] is False
    assert evidence["skipped_reason"] == "semantic_disabled"
    assert evidence["entries"] == []


def test_score_jobs_semantic_sidecar_mode_does_not_mutate_scores(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    fixture = repo_root / "tests" / "fixtures" / "openai_enriched_jobs.sample.json"

    baseline_dir = tmp_path / "baseline"
    baseline_dir.mkdir(parents=True, exist_ok=True)
    baseline_json = baseline_dir / "ranked.json"

    sidecar_dir = tmp_path / "sidecar"
    sidecar_dir.mkdir(parents=True, exist_ok=True)
    sidecar_json = sidecar_dir / "ranked.json"
    semantic_out = sidecar_dir / "semantic_scores.json"

    base_cmd = [
        sys.executable,
        "scripts/score_jobs.py",
        "--profile",
        "cs",
        "--in_path",
        str(fixture),
        "--out_json",
        str(baseline_json),
        "--out_csv",
        str(baseline_dir / "ranked.csv"),
        "--out_families",
        str(baseline_dir / "families.json"),
        "--out_md",
        str(baseline_dir / "shortlist.md"),
    ]
    subprocess.run(base_cmd, cwd=repo_root, check=True)

    sidecar_cmd = [
        sys.executable,
        "scripts/score_jobs.py",
        "--profile",
        "cs",
        "--in_path",
        str(fixture),
        "--out_json",
        str(sidecar_json),
        "--out_csv",
        str(sidecar_dir / "ranked.csv"),
        "--out_families",
        str(sidecar_dir / "families.json"),
        "--out_md",
        str(sidecar_dir / "shortlist.md"),
        "--semantic_scores_out",
        str(semantic_out),
    ]
    env = dict(os.environ)
    env["SEMANTIC_ENABLED"] = "1"
    env["SEMANTIC_MODE"] = "sidecar"
    subprocess.run(sidecar_cmd, cwd=repo_root, check=True, env=env)

    assert baseline_json.read_text(encoding="utf-8") == sidecar_json.read_text(encoding="utf-8")
    evidence = json.loads(semantic_out.read_text(encoding="utf-8"))
    assert evidence["enabled"] is False
    assert evidence["skipped_reason"] == "semantic_disabled"
