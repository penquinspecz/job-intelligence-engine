import importlib
import os
import sys
from pathlib import Path

import ji_engine.config as config
import scripts.run_daily as run_daily


def test_no_subprocess_logs_stages(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    snapshot = data_dir / "openai_snapshots" / "index.html"
    snapshot.parent.mkdir(parents=True)
    snapshot.write_text("snapshot")

    state_dir = tmp_path / "state"
    monkeypatch.setenv("JOBINTEL_DATA_DIR", str(data_dir))
    monkeypatch.setenv("JOBINTEL_STATE_DIR", str(state_dir))
    importlib.reload(config)
    importlib.reload(run_daily)
    stages = []
    def fake_run(cmd, *, stage):
        stages.append(stage)
        # Create expected output files for each stage
        if stage == "scrape":
            raw_path = data_dir / "openai_raw_jobs.json"
            raw_path.parent.mkdir(parents=True, exist_ok=True)
            raw_path.write_text("[]", encoding="utf-8")
        elif stage == "classify":
            labeled_path = data_dir / "openai_labeled_jobs.json"
            labeled_path.parent.mkdir(parents=True, exist_ok=True)
            labeled_path.write_text("[]", encoding="utf-8")
        elif stage == "enrich":
            enriched_path = data_dir / "openai_enriched_jobs.json"
            enriched_path.parent.mkdir(parents=True, exist_ok=True)
            enriched_path.write_text("[]", encoding="utf-8")
        elif stage.startswith("score:"):
            profile = stage.split(":", 1)[1]
            for path in (
                run_daily.ranked_jobs_json(profile),
                run_daily.ranked_jobs_csv(profile),
                run_daily.ranked_families_json(profile),
                run_daily.shortlist_md_path(profile),
            ):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("[]", encoding="utf-8")

    monkeypatch.setattr(run_daily, "_run", fake_run)
    monkeypatch.setattr(run_daily.subprocess, "run", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("subprocess should not run")))
    monkeypatch.setattr(sys, "argv", ["run_daily.py", "--no_subprocess", "--profiles", "cs", "--us_only", "--no_post"])
    rc = run_daily.main()

    assert rc == 0
    assert "scrape" in stages
    assert "classify" in stages
    assert "enrich" in stages
    assert "score:cs" in stages
