from __future__ import annotations

import json
import sys
from pathlib import Path

import scripts.run_daily as run_daily


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _arg_value(cmd: list[str], flag: str) -> str:
    return cmd[cmd.index(flag) + 1]


def _configure_common(monkeypatch, tmp_path: Path) -> tuple[Path, Path, Path]:
    data_dir = tmp_path / "data"
    output_dir = data_dir / "ashby_cache"
    snapshot_dir = data_dir / "openai_snapshots"
    state_dir = tmp_path / "state"
    output_dir.mkdir(parents=True, exist_ok=True)
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    state_dir.mkdir(parents=True, exist_ok=True)
    (snapshot_dir / "index.html").write_text("<html>snapshot</html>", encoding="utf-8")
    _write_json(data_dir / "candidate_profile.json", {"summary": "customer success profile"})

    monkeypatch.setattr(run_daily, "DATA_DIR", data_dir)
    monkeypatch.setattr(run_daily, "STATE_DIR", state_dir)
    monkeypatch.setattr(run_daily, "RUN_METADATA_DIR", state_dir / "runs")
    monkeypatch.setattr(run_daily, "LAST_RUN_JSON", state_dir / "last_run.json")
    monkeypatch.setattr(run_daily, "LAST_SUCCESS_JSON", state_dir / "last_success.json")
    monkeypatch.setattr(run_daily, "LOCK_PATH", state_dir / "lock")
    monkeypatch.setattr(run_daily, "SNAPSHOT_DIR", snapshot_dir)
    run_daily.USE_SUBPROCESS = False

    original_archive_input = run_daily._archive_input

    def _archive_input_with_test_state(*args, **kwargs):
        kwargs["state_dir"] = state_dir
        return original_archive_input(*args, **kwargs)

    monkeypatch.setattr(run_daily, "_archive_input", _archive_input_with_test_state)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_daily.py",
            "--no_subprocess",
            "--providers",
            "openai",
            "--profiles",
            "cs",
            "--offline",
            "--snapshot-only",
            "--no_post",
        ],
    )
    return data_dir, output_dir, state_dir


def _fake_run_factory(*, output_dir: Path, state_dir: Path, ai_tokens: int) -> callable:
    def fake_run(cmd, *, stage):
        if stage == "scrape":
            _write_json(
                output_dir / "openai_raw_jobs.json",
                [{"job_id": "job-1", "title": "Customer Success Architect", "apply_url": "https://example.com/1"}],
            )
            _write_json(output_dir / "openai_scrape_meta.json", {"provider": "openai", "scrape_mode": "snapshot"})
            return
        if stage == "classify":
            _write_json(
                output_dir / "openai_labeled_jobs.json",
                [{"job_id": "job-1", "title": "Customer Success Architect", "apply_url": "https://example.com/1"}],
            )
            return
        if stage == "enrich":
            _write_json(
                output_dir / "openai_enriched_jobs.json",
                [{"job_id": "job-1", "title": "Customer Success Architect", "apply_url": "https://example.com/1"}],
            )
            return
        if stage.startswith("score:"):
            out_json = Path(_arg_value(cmd, "--out_json"))
            out_csv = Path(_arg_value(cmd, "--out_csv"))
            out_families = Path(_arg_value(cmd, "--out_families"))
            out_md = Path(_arg_value(cmd, "--out_md"))
            out_top = Path(_arg_value(cmd, "--out_md_top_n"))
            semantic_out = Path(_arg_value(cmd, "--semantic_scores_out"))
            _write_json(out_json, [{"job_id": "job-1", "score": 80, "title": "Customer Success Architect"}])
            out_csv.parent.mkdir(parents=True, exist_ok=True)
            out_csv.write_text("job_id,score\njob-1,80\n", encoding="utf-8")
            _write_json(out_families, [])
            out_md.write_text("# shortlist\n", encoding="utf-8")
            out_top.write_text("# top\n", encoding="utf-8")
            _write_json(
                semantic_out,
                {
                    "enabled": False,
                    "model_id": "deterministic-hash-v1",
                    "cache_hit_counts": {"hit": 0, "miss": 0, "write": 0, "profile_hit": 0, "profile_miss": 0},
                    "entries": [],
                    "skipped_reason": "semantic_disabled",
                },
            )
            return
        if stage.startswith("ai_insights:"):
            run_id = _arg_value(cmd, "--run_id")
            run_dir = state_dir / "runs" / run_daily._sanitize_run_id(run_id)
            _write_json(
                run_dir / "ai_insights.cs.json",
                {
                    "status": "ok",
                    "provider": "openai",
                    "profile": "cs",
                    "structured_input": {"rolling_diff_counts_7": {"totals": {"new": 1, "changed": 0, "removed": 0}}},
                    "metadata": {},
                },
            )
            return
        if stage.startswith("ai_job_briefs:"):
            run_id = _arg_value(cmd, "--run_id")
            run_dir = state_dir / "runs" / run_daily._sanitize_run_id(run_id)
            _write_json(
                run_dir / "ai_job_briefs.cs.json",
                {
                    "status": "ok",
                    "briefs": [{"job_id": "job-1"}],
                    "metadata": {"estimated_tokens_used": ai_tokens},
                },
            )
            return

    return fake_run


def test_run_daily_token_cap_guardrail_exits_2_and_writes_costs(tmp_path: Path, monkeypatch) -> None:
    _, output_dir, state_dir = _configure_common(monkeypatch, tmp_path)
    monkeypatch.setenv("JOBINTEL_RUN_ID", "cost-guardrail")
    monkeypatch.setenv("AI_ENABLED", "1")
    monkeypatch.setenv("AI_JOB_BRIEFS_ENABLED", "1")
    monkeypatch.setenv("MAX_AI_TOKENS_PER_RUN", "10")
    monkeypatch.setattr(run_daily, "_run", _fake_run_factory(output_dir=output_dir, state_dir=state_dir, ai_tokens=50))

    rc = run_daily.main()
    assert rc == 2

    run_dir = state_dir / "runs" / "costguardrail"
    costs = json.loads((run_dir / "costs.json").read_text(encoding="utf-8"))
    report = json.loads((run_dir / "run_report.json").read_text(encoding="utf-8"))
    assert costs["ai_estimated_tokens"] > 10
    assert report["status"] == "error"
    assert report["failed_stage"] == "cost_guardrails"


def test_run_daily_writes_cost_artifact(tmp_path: Path, monkeypatch) -> None:
    _, output_dir, state_dir = _configure_common(monkeypatch, tmp_path)
    monkeypatch.setenv("JOBINTEL_RUN_ID", "cost-artifact")
    monkeypatch.setenv("AI_ENABLED", "1")
    monkeypatch.setenv("AI_JOB_BRIEFS_ENABLED", "1")
    monkeypatch.setattr(run_daily, "_run", _fake_run_factory(output_dir=output_dir, state_dir=state_dir, ai_tokens=8))

    rc = run_daily.main()
    assert rc == 0

    run_dir = state_dir / "runs" / "costartifact"
    costs = json.loads((run_dir / "costs.json").read_text(encoding="utf-8"))
    assert set(costs.keys()) == {
        "embeddings_count",
        "embeddings_estimated_tokens",
        "ai_calls",
        "ai_estimated_tokens",
        "total_estimated_tokens",
    }
    assert costs["ai_calls"] >= 1
    assert costs["total_estimated_tokens"] == costs["embeddings_estimated_tokens"] + costs["ai_estimated_tokens"]
