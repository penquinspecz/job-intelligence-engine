from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_ai_shortlist_md_includes_ai_fields(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]

    jobs = [
        {
            "title": "Role A",
            "jd_text": "desc",
            "apply_url": "a",
            "ai": {
                "match_score": 80,
                "skills_required": ["python", "apis"],
                "skills_preferred": ["ml"],
                "red_flags": ["requires clearance"],
            },
        },
        {
            "title": "Role B",
            "jd_text": "desc",
            "apply_url": "b",
            "ai": {
                "match_score": 10,
                "skills_required": ["excel"],
                "skills_preferred": [],
                "red_flags": [],
            },
        },
    ]

    input_path = tmp_path / "in.json"
    out_json = tmp_path / "ranked.json"
    out_csv = tmp_path / "ranked.csv"
    out_families = tmp_path / "families.json"
    out_md = tmp_path / "shortlist.md"
    out_md_ai = tmp_path / "shortlist_ai.md"

    input_path.write_text(json.dumps(jobs), encoding="utf-8")

    cmd = [
        sys.executable,
        "scripts/score_jobs.py",
        "--profile",
        "cs",
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
        "--out_md_ai",
        str(out_md_ai),
        "--shortlist_score",
        "0",
    ]

    subprocess.run(cmd, cwd=repo_root, check=True)

    content = out_md_ai.read_text(encoding="utf-8")
    assert "Match score: 80" in content
    assert "Skills required: python, apis" in content
    assert "Skills preferred: ml" in content
    assert "Red flags:" in content
    assert "requires clearance" in content
    assert "Explanation:" in content

