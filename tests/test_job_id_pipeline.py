import importlib
import json
import sys
from pathlib import Path

import ji_engine.config as config
import scripts.run_classify as run_classify
import scripts.score_jobs as score_jobs


def test_job_id_persisted_in_ranked_and_shortlist(tmp_path, monkeypatch) -> None:
    data_dir = tmp_path / "data"
    state_dir = tmp_path / "state"
    monkeypatch.setenv("JOBINTEL_DATA_DIR", str(data_dir))
    monkeypatch.setenv("JOBINTEL_STATE_DIR", str(state_dir))
    importlib.reload(config)
    importlib.reload(run_classify)
    importlib.reload(score_jobs)

    raw_path = data_dir / "openai_raw_jobs.json"
    labeled_path = data_dir / "openai_labeled_jobs.json"
    out_json = data_dir / "openai_ranked_jobs.cs.json"
    out_csv = data_dir / "openai_ranked_jobs.cs.csv"
    out_families = data_dir / "openai_ranked_families.cs.json"
    out_md = data_dir / "openai_shortlist.cs.md"

    job_id = "0c22b805-3976-492e-81f2-7cf91f63a630"
    apply_url = f"https://jobs.ashbyhq.com/openai/{job_id}/application"
    raw_jobs = [
        {
            "source": "openai",
            "title": "Customer Success Manager",
            "location": "Remote - US",
            "team": "CS",
            "apply_url": apply_url,
            "detail_url": None,
            "raw_text": "Role A",
            "scraped_at": "2024-01-01T00:00:00",
        }
    ]
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_text(json.dumps(raw_jobs, indent=2), encoding="utf-8")

    rc = run_classify.main(["--in_path", str(raw_path), "--out_path", str(labeled_path)])
    assert rc == 0

    score_args = [
        "score_jobs.py",
        "--profile",
        "cs",
        "--profiles",
        "config/profiles.json",
        "--in_path",
        str(labeled_path),
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
    ]
    monkeypatch.setattr(sys, "argv", score_args)
    score_rc = score_jobs.main()
    assert score_rc == 0

    ranked = json.loads(out_json.read_text(encoding="utf-8"))
    assert ranked[0]["job_id"] == job_id

    shortlist_text = out_md.read_text(encoding="utf-8")
    assert f"(job_id: {job_id})" in shortlist_text
