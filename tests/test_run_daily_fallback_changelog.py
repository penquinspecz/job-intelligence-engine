import importlib
import json
import sys

import ji_engine.config as config
import scripts.run_daily as run_daily


def test_us_only_fallback_suppresses_changelog_and_alerts(tmp_path, monkeypatch) -> None:
    data_dir = tmp_path / "data"
    state_dir = tmp_path / "state"
    monkeypatch.setenv("JOBINTEL_DATA_DIR", str(data_dir))
    monkeypatch.setenv("JOBINTEL_STATE_DIR", str(state_dir))
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "")
    snapshot = data_dir / "openai_snapshots" / "index.html"
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    snapshot.write_text("<html></html>", encoding="utf-8")
    importlib.reload(config)
    importlib.reload(run_daily)
    run_daily.USE_SUBPROCESS = False

    alert_called = {"called": False}

    monkeypatch.setattr(run_daily, "_post_discord", lambda *args, **kwargs: False)

    def fake_dispatch(*args, **kwargs) -> None:
        alert_called["called"] = True
        raise AssertionError("Alerts should be suppressed when fallback_applied is True.")

    output_dir = data_dir / "ashby_cache"

    def fake_run(cmd, *, stage):
        if stage == "scrape":
            raw_path = output_dir / "openai_raw_jobs.json"
            raw_path.parent.mkdir(parents=True, exist_ok=True)
            raw_path.write_text("[]", encoding="utf-8")
            return
        if stage == "classify":
            labeled_path = output_dir / "openai_labeled_jobs.json"
            labeled_path.parent.mkdir(parents=True, exist_ok=True)
            labeled_path.write_text("[]", encoding="utf-8")
            return
        if stage == "enrich":
            enriched_path = output_dir / "openai_enriched_jobs.json"
            enriched_path.parent.mkdir(parents=True, exist_ok=True)
            enriched_path.write_text("[]", encoding="utf-8")
            return
        if stage.startswith("score:"):
            profile = stage.split(":", 1)[1]
            ranked_json = run_daily._provider_ranked_jobs_json("openai", profile)
            ranked_csv = run_daily._provider_ranked_jobs_csv("openai", profile)
            ranked_families = run_daily._provider_ranked_families_json("openai", profile)
            shortlist_md = run_daily._provider_shortlist_md("openai", profile)
            jobs = [
                {"title": "A Role", "apply_url": "https://example.com/a", "score": 95},
                {"title": "B Role", "apply_url": "https://example.com/b", "score": 90},
            ]
            for path in (ranked_json, ranked_csv, ranked_families, shortlist_md):
                path.parent.mkdir(parents=True, exist_ok=True)
            ranked_json.write_text(json.dumps(jobs), encoding="utf-8")
            ranked_csv.write_text("[]", encoding="utf-8")
            ranked_families.write_text("[]", encoding="utf-8")
            shortlist_md.write_text("# Shortlist\n", encoding="utf-8")
            meta_path = run_daily._score_meta_path(ranked_json)
            meta_path.write_text(
                json.dumps({"us_only_fallback": {"fallback_applied": True}}),
                encoding="utf-8",
            )

    monkeypatch.setattr(run_daily, "_dispatch_alerts", fake_dispatch)
    monkeypatch.setattr(run_daily, "_run", fake_run)
    monkeypatch.setattr(
        sys, "argv", ["run_daily.py", "--no_subprocess", "--no_enrich", "--profiles", "cs", "--us_only"]
    )
    rc = run_daily.main()

    assert rc == 0
    assert alert_called["called"] is False

    metadata_files = sorted(run_daily.RUN_METADATA_DIR.glob("*.json"))
    assert metadata_files
    data = run_daily._read_json(metadata_files[-1])
    diff_counts = data["diff_counts"]["cs"]
    assert diff_counts["new"] == 0
    assert diff_counts["changed"] == 0
    assert diff_counts["removed"] == 0
    assert diff_counts["suppressed"] is True
    assert diff_counts["reason"] == "us_only_fallback"
