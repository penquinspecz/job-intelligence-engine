from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def run_score_jobs(tmp_path: Path) -> list[dict]:
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
    return json.loads(out_json.read_text(encoding="utf-8"))


def test_score_jobs_golden_master(tmp_path: Path) -> None:
    ranked = run_score_jobs(tmp_path)

    assert len(ranked) == 20  # fixture count

    titles = [j["title"] for j in ranked[:10]]
    scores = [j.get("score") for j in ranked[:10]]
    heuristic_scores = [j.get("heuristic_score") for j in ranked[:10]]
    final_scores = [j.get("final_score") for j in ranked[:10]]

    expected_titles = [
        "Manager, AI Deployment - AMER",
        "Partner Solutions Architect",
        "Forward Deployed Software Engineer - Munich",
        "Forward Deployed Software Engineer - NYC",
        "Forward Deployed Software Engineer - SF",
        "Forward Deployed Engineer, Gov",
        "Forward Deployed Engineer - Life Sciences - NYC",
        "Forward Deployed Engineer - Life Sciences - SF",
        "Solution Architect Manager, Digital Natives",
        "Forward Deployed Engineer - Financial Services",
    ]

    expected_scores = [146, 132, 105, 105, 105, 100, 98, 98, 98, 94]

    assert titles == expected_titles
    assert scores == expected_scores
    assert heuristic_scores == expected_scores  # no AI payload in fixture
    assert final_scores == expected_scores

