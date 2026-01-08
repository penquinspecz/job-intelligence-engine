from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_explain_top_prints_expected_columns(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]

    jobs = [
        {"title": "Role A", "jd_text": "", "apply_url": "a", "ai": {"match_score": 10}},
        {"title": "Role B", "jd_text": "", "apply_url": "b"},
    ]
    input_path = tmp_path / "in.json"
    out_json = tmp_path / "ranked.json"
    out_csv = tmp_path / "ranked.csv"
    out_families = tmp_path / "families.json"
    out_md = tmp_path / "shortlist.md"

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
        "--shortlist_score",
        "0",
        "--explain_top",
        "1",
    ]
    proc = subprocess.run(cmd, cwd=repo_root, check=True, capture_output=True, text=True)

    # Header line must include expected columns (TSV).
    header = (proc.stdout.splitlines() or [""])[0]
    assert header == "\t".join(
        [
            "title",
            "heuristic_score",
            "ai_match_score",
            "blend_weight_used",
            "final_score",
            "ai_influenced",
        ]
    )

