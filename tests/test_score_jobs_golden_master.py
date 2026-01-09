from __future__ import annotations

import json
import subprocess
import sys
import csv
from pathlib import Path


def run_score_jobs(tmp_path: Path) -> tuple[list[dict], list[str]]:
    repo_root = Path(__file__).resolve().parents[1]
    fixture = repo_root / "tests" / "fixtures" / "openai_enriched_jobs.sample.json"

    out_json = tmp_path / "ranked.json"
    out_csv = tmp_path / "ranked.csv"
    out_families = tmp_path / "families.json"
    out_md = tmp_path / "shortlist.md"

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
    return ranked, headers


def test_score_jobs_golden_master(tmp_path: Path) -> None:
    ranked, headers = run_score_jobs(tmp_path)

    assert len(ranked) == 20  # fixture count

    titles = [j["title"] for j in ranked[:10]]
    scores = [j.get("score") for j in ranked[:10]]
    heuristic_scores = [j.get("heuristic_score") for j in ranked[:10]]
    final_scores = [j.get("final_score") for j in ranked[:10]]

    expected_titles = [
        "Manager, AI Deployment - AMER",
        "Partner Solutions Architect",
        "Forward Deployed Software Engineer - SF",
        "Forward Deployed Software Engineer - Munich",
        "Forward Deployed Software Engineer - NYC",
        "Forward Deployed Engineer, Gov",
        "Forward Deployed Engineer - Life Sciences - SF",
        "Forward Deployed Engineer - Life Sciences - NYC",
        "Solution Architect Manager, Digital Natives",
        "Forward Deployed Engineer - Munich",
    ]

    expected_scores = [146, 132, 105, 105, 105, 100, 98, 98, 98, 94]

    assert titles == expected_titles
    assert scores == expected_scores
    assert heuristic_scores == expected_scores  # no AI payload in fixture
    assert final_scores == expected_scores

    # Verify stable sort: for tied scores, apply_url is non-decreasing
    for i in range(len(ranked) - 1):
        curr_score = ranked[i].get("score", 0)
        next_score = ranked[i + 1].get("score", 0)
        if curr_score == next_score:
            curr_url = ranked[i].get("apply_url", "")
            next_url = ranked[i + 1].get("apply_url", "")
            assert curr_url <= next_url, f"Tied scores at index {i}, {i+1} not ordered by apply_url"

    # Explanations exist and are well-formed; should not affect ordering/scores.
    assert "explanation_summary" in headers
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

