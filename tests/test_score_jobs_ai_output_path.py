import json
import sys
from pathlib import Path

import scripts.score_jobs as score_jobs


def test_score_jobs_ai_md_uses_out_md_dir(tmp_path: Path, monkeypatch) -> None:
    in_path = tmp_path / "input.json"
    in_path.write_text(
        json.dumps(
            [
                {
                    "title": "Software Engineer",
                    "location": "Remote",
                    "apply_url": "https://example.com/apply",
                    "job_id": "job-1",
                    "jd_text": "Build things",
                    "enrich_status": "ok",
                }
            ]
        ),
        encoding="utf-8",
    )

    out_md = tmp_path / "openai_shortlist.cs.md"
    out_json = tmp_path / "ranked.json"
    out_csv = tmp_path / "ranked.csv"
    out_families = tmp_path / "families.json"

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "score_jobs.py",
            "--profile",
            "cs",
            "--in_path",
            str(in_path),
            "--out_json",
            str(out_json),
            "--out_csv",
            str(out_csv),
            "--out_families",
            str(out_families),
            "--out_md",
            str(out_md),
        ],
    )

    assert score_jobs.main() == 0
    expected_ai = tmp_path / "openai_shortlist.cs_ai.md"
    assert expected_ai.exists()
