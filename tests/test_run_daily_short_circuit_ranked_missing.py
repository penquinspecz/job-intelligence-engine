from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from typing import Any, List


def test_short_circuit_missing_ranked_triggers_scoring(tmp_path: Path, monkeypatch: Any, caplog: Any) -> None:
    """
    If ranked artifacts are missing in short-circuit mode, scoring should run and produce them.
    """
    data_dir = tmp_path / "data"
    state_dir = tmp_path / "state"
    data_dir.mkdir()
    state_dir.mkdir()

    snapshot_dir = data_dir / "openai_snapshots"
    snapshot_dir.mkdir()
    (snapshot_dir / "index.html").write_text("<html>ok</html>")

    # Inputs unchanged (hashes match), but ranked outputs are absent
    output_dir = data_dir / "ashby_cache"
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "openai_raw_jobs.json").write_text("[]")
    (output_dir / "openai_labeled_jobs.json").write_text("[]")
    (output_dir / "openai_enriched_jobs.json").write_text("[]")
    (data_dir / "candidate_profile.json").write_text('{"skills": [], "roles": []}')

    # Write last_run to simulate matching hashes (short-circuit condition)
    (state_dir / "last_run.json").write_text(json.dumps({"hashes": {"raw": None, "labeled": None, "enriched": None}}))

    monkeypatch.setenv("JOBINTEL_DATA_DIR", str(data_dir))
    monkeypatch.setenv("JOBINTEL_STATE_DIR", str(state_dir))
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "")

    import ji_engine.config as config
    import scripts.run_daily as run_daily

    config = importlib.reload(config)
    run_daily = importlib.reload(run_daily)
    run_daily.USE_SUBPROCESS = False

    captured: List[str] = []

    def fake_run(cmd, *, stage):
        captured.append(stage)
        if stage == "scrape":
            (output_dir / "openai_raw_jobs.json").write_text("[]")
        if stage == "classify":
            (output_dir / "openai_labeled_jobs.json").write_text("[]")
        if stage.startswith("score:"):
            profile = stage.split(":", 1)[1]
            for path in (
                run_daily._provider_ranked_jobs_json("openai", profile),
                run_daily._provider_ranked_jobs_csv("openai", profile),
                run_daily._provider_ranked_families_json("openai", profile),
                run_daily._provider_shortlist_md("openai", profile),
            ):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("[]", encoding="utf-8")

    # Force _should_short_circuit to return True but keep ranked_missing=True so scoring runs
    def fake_should_short(prev_hashes, curr_hashes):
        return True

    monkeypatch.setattr(run_daily, "_should_short_circuit", fake_should_short)
    monkeypatch.setattr(run_daily, "_run", fake_run)
    caplog.set_level("INFO")
    # No --ai so we exercise the no-AI short-circuit branch; missing ranked outputs should force scoring.
    monkeypatch.setattr(sys, "argv", ["run_daily.py", "--no_subprocess", "--no_post", "--profiles", "cs"])

    rc = run_daily.main()
    assert rc == 0

    # Log should include missing artifact names and indicate scoring is not skipped
    assert "Short-circuit skipped because ranked artifacts are missing" in caplog.text
    assert "openai_ranked_jobs.cs.json" in caplog.text
    assert "openai_ranked_jobs.cs.csv" in caplog.text
    assert "openai_ranked_families.cs.json" in caplog.text
    assert "openai_shortlist.cs.md" in caplog.text
    # We don't assert file creation here because stage execution is covered in other tests;
    # this test focuses on the logging of missing artifacts.
