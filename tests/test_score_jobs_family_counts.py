from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_family_counts_prints_known_families(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]

    # Keep heuristic scores tied so ranking order is stable (input order).
    jobs = [
        {"title": "Role A", "jd_text": "", "apply_url": "a", "ai": {"match_score": 0, "role_family": "Customer Success", "seniority": "Senior"}},
        {"title": "Role B", "jd_text": "", "apply_url": "b", "ai": {"match_score": 0, "role_family": "Solutions Architect", "seniority": "IC"}},
        {"title": "Role C", "jd_text": "", "apply_url": "c", "ai": {"match_score": 0, "role_family": "Forward Deployed", "seniority": "IC"}},
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
        "--family_counts",
    ]
    proc = subprocess.run(cmd, cwd=repo_root, check=True, capture_output=True, text=True)

    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    assert lines[0] == "role_family\tcount"
    # Order is first-seen (top-to-bottom).
    assert lines[1].startswith("Customer Success\t")
    assert lines[2].startswith("Solutions Architect\t")
    assert lines[3].startswith("Forward Deployed\t")

