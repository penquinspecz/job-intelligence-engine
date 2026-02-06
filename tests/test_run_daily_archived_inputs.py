import importlib
import json
import sys
from pathlib import Path

import ji_engine.config as config
import scripts.replay_run as replay_run
import scripts.run_daily as run_daily
from ji_engine.utils.verification import compute_sha256_file


def test_run_daily_archives_selected_inputs_and_replay(tmp_path, monkeypatch) -> None:
    data_dir = tmp_path / "data"
    state_dir = tmp_path / "state"
    snapshot = data_dir / "openai_snapshots" / "index.html"
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    snapshot.write_text("snapshot", encoding="utf-8")

    monkeypatch.setenv("JOBINTEL_DATA_DIR", str(data_dir))
    monkeypatch.setenv("JOBINTEL_STATE_DIR", str(state_dir))
    importlib.reload(config)
    importlib.reload(run_daily)
    importlib.reload(replay_run)

    output_dir = data_dir / "ashby_cache"

    def fake_run(cmd, *, stage):
        if stage == "scrape":
            raw_path = output_dir / "openai_raw_jobs.json"
            raw_path.parent.mkdir(parents=True, exist_ok=True)
            raw_path.write_text("[]", encoding="utf-8")
        elif stage == "classify":
            labeled_path = output_dir / "openai_labeled_jobs.json"
            labeled_path.parent.mkdir(parents=True, exist_ok=True)
            labeled_path.write_text("[]", encoding="utf-8")
        elif stage == "enrich":
            enriched_path = output_dir / "openai_enriched_jobs.json"
            enriched_path.parent.mkdir(parents=True, exist_ok=True)
            enriched_path.write_text("[]", encoding="utf-8")
        elif stage.startswith("score:"):
            profile = stage.split(":", 1)[1]
            for path in (
                run_daily._provider_ranked_jobs_json("openai", profile),
                run_daily._provider_ranked_jobs_csv("openai", profile),
                run_daily._provider_ranked_families_json("openai", profile),
                run_daily._provider_shortlist_md("openai", profile),
            ):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("[]", encoding="utf-8")

    monkeypatch.setattr(run_daily, "_run", fake_run)
    monkeypatch.setattr(sys, "argv", ["run_daily.py", "--no_subprocess", "--profiles", "cs", "--us_only", "--no_post"])

    rc = run_daily.main()
    assert rc == 0

    metadata_files = sorted(run_daily.RUN_METADATA_DIR.glob("*.json"))
    assert metadata_files
    run_report = json.loads(metadata_files[-1].read_text(encoding="utf-8"))
    run_id = run_report["run_id"]
    run_dir = run_daily.RUN_METADATA_DIR / run_daily._sanitize_run_id(run_id)

    archived = run_report["archived_inputs_by_provider_profile"]["openai"]["cs"]
    archived_input = archived["selected_scoring_input"]
    archived_path = state_dir / Path(archived_input["archived_path"])
    assert archived_path.exists()
    assert archived_input["sha256"] == compute_sha256_file(archived_path)

    # Overwrite canonical input in data dir; archived copy should remain stable.
    (data_dir / "openai_enriched_jobs.json").write_text("junk", encoding="utf-8")
    assert archived_input["sha256"] == compute_sha256_file(archived_path)

    report_path = run_dir / "run_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    exit_code, lines, _artifacts, _counts = replay_run._replay_report(report, "cs", strict=True, state_dir=state_dir)
    assert exit_code == 0
    assert any(line.startswith("PASS:") for line in lines)
