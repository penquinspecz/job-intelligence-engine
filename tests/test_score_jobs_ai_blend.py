from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_ai_blend_affects_order(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]

    jobs = [
        {
            "title": "Role A",
            "jd_text": "",
            "apply_url": "a",
            "ai": {"match_score": 90},
        },
        {
            "title": "Role B",
            "jd_text": "",
            "apply_url": "b",
            "ai": {"match_score": 10},
        },
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
    ]

    subprocess.run(cmd, cwd=repo_root, check=True)

    ranked = json.loads(out_json.read_text(encoding="utf-8"))
    assert ranked[0]["title"] == "Role A"
    assert ranked[1]["title"] == "Role B"

    # Heuristic scores equal (no text), final should reflect AI blend
    assert ranked[0]["heuristic_score"] == ranked[1]["heuristic_score"] == 0
    assert ranked[0]["final_score"] > ranked[1]["final_score"]
    assert ranked[0]["final_score"] == int(round(0.35 * 90))

