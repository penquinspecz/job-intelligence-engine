import importlib
import sys
from pathlib import Path

import ji_engine.config as config
import scripts.run_daily as run_daily


def test_run_daily_uses_output_dir_for_classify(monkeypatch, tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    state_dir = tmp_path / "state"
    snapshot = data_dir / "openai_snapshots" / "index.html"
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    snapshot.write_text("<html>snapshot</html>", encoding="utf-8")

    monkeypatch.setenv("JOBINTEL_DATA_DIR", str(data_dir))
    monkeypatch.setenv("JOBINTEL_STATE_DIR", str(state_dir))
    monkeypatch.delenv("JOBINTEL_OUTPUT_DIR", raising=False)
    importlib.reload(config)
    importlib.reload(run_daily)

    expected_output = data_dir / "ashby_cache"
    classify_cmd: dict = {}

    def fake_run(cmd, *, stage):
        if stage == "scrape":
            raw_path = expected_output / "openai_raw_jobs.json"
            raw_path.parent.mkdir(parents=True, exist_ok=True)
            raw_path.write_text("[]", encoding="utf-8")
        elif stage == "classify":
            classify_cmd["cmd"] = cmd
            labeled_path = expected_output / "openai_labeled_jobs.json"
            labeled_path.parent.mkdir(parents=True, exist_ok=True)
            labeled_path.write_text("[]", encoding="utf-8")
        elif stage == "enrich":
            enriched_path = expected_output / "openai_enriched_jobs.json"
            enriched_path.parent.mkdir(parents=True, exist_ok=True)
            enriched_path.write_text("[]", encoding="utf-8")
        elif stage.startswith("score:"):
            profile = stage.split(":", 1)[1]
            for path in (
                run_daily._provider_ranked_jobs_json("openai", profile),
                run_daily._provider_ranked_jobs_csv("openai", profile),
                run_daily._provider_ranked_families_json("openai", profile),
                run_daily._provider_shortlist_md("openai", profile),
                run_daily._provider_top_md("openai", profile),
            ):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("[]", encoding="utf-8")

    monkeypatch.setattr(run_daily, "_run", fake_run)
    monkeypatch.setattr(run_daily, "USE_SUBPROCESS", False)
    monkeypatch.setattr(sys, "argv", ["run_daily.py", "--no_subprocess", "--profiles", "cs", "--no_post", "--us_only"])

    rc = run_daily.main()
    assert rc == 0

    cmd = classify_cmd["cmd"]
    in_path = Path(cmd[cmd.index("--in_path") + 1])
    out_path = Path(cmd[cmd.index("--out_path") + 1])
    assert in_path == expected_output / "openai_raw_jobs.json"
    assert out_path == expected_output / "openai_labeled_jobs.json"
