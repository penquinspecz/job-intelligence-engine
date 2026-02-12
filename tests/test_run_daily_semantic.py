from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import scripts.run_daily as run_daily


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_run_daily_writes_semantic_summary_when_disabled(tmp_path: Path, monkeypatch) -> None:
    data_dir = tmp_path / "data"
    output_dir = data_dir / "ashby_cache"
    state_dir = tmp_path / "state"
    output_dir.mkdir(parents=True, exist_ok=True)
    state_dir.mkdir(parents=True, exist_ok=True)

    _write_json(data_dir / "candidate_profile.json", {"roles": ["cs"]})
    _write_json(output_dir / "openai_raw_jobs.json", [{"id": 1}])
    _write_json(output_dir / "openai_labeled_jobs.json", [{"id": 1}])
    _write_json(output_dir / "openai_enriched_jobs.json", [{"id": 1}])

    monkeypatch.setenv("SEMANTIC_ENABLED", "0")
    monkeypatch.setattr(run_daily, "DATA_DIR", data_dir)
    monkeypatch.setattr(run_daily, "STATE_DIR", state_dir)
    monkeypatch.setattr(run_daily, "RUN_METADATA_DIR", state_dir / "runs")
    monkeypatch.setattr(run_daily, "LAST_RUN_JSON", state_dir / "last_run.json")
    monkeypatch.setattr(run_daily, "LAST_SUCCESS_JSON", state_dir / "last_success.json")
    monkeypatch.setattr(run_daily, "LOCK_PATH", state_dir / "lock")
    monkeypatch.setattr(run_daily, "_run", lambda *a, **k: None)
    monkeypatch.setattr(run_daily, "_resolve_profiles", lambda args: [])
    monkeypatch.setattr(run_daily, "_utcnow_iso", lambda: "2026-01-02T00:00:00Z")

    run_daily.USE_SUBPROCESS = False
    monkeypatch.setattr(sys, "argv", ["run_daily.py", "--no_subprocess", "--profile", "cs", "--no_post"])

    rc = run_daily.main()
    assert rc == 0

    summary_path = state_dir / "runs" / "20260102T000000Z" / "semantic" / "semantic_summary.json"
    assert summary_path.exists()
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["enabled"] is False
    assert summary["skipped_reason"] == "semantic_disabled"


def test_semantic_enabled_bypasses_short_circuit_and_writes_artifacts(tmp_path: Path, monkeypatch) -> None:
    data_dir = tmp_path / "data"
    output_dir = data_dir / "ashby_cache"
    snapshot_dir = data_dir / "openai_snapshots"
    state_dir = tmp_path / "state"
    output_dir.mkdir(parents=True, exist_ok=True)
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    state_dir.mkdir(parents=True, exist_ok=True)
    (snapshot_dir / "index.html").write_text("<html>snapshot</html>", encoding="utf-8")

    _write_json(data_dir / "candidate_profile.json", {"summary": "customer success architect"})

    score_stage_calls: list[str] = []
    non_score_stages: list[str] = []

    def _arg_value(cmd: list[str], flag: str) -> str:
        return cmd[cmd.index(flag) + 1]

    def fake_run(cmd, *, stage):
        non_score_stages.append(stage)
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
            score_stage_calls.append(stage)
            out_json = Path(_arg_value(cmd, "--out_json"))
            out_csv = Path(_arg_value(cmd, "--out_csv"))
            out_families = Path(_arg_value(cmd, "--out_families"))
            out_md = Path(_arg_value(cmd, "--out_md"))
            out_top = Path(_arg_value(cmd, "--out_md_top_n"))
            semantic_out = Path(_arg_value(cmd, "--semantic_scores_out"))
            ranked = [{"job_id": "job-1", "score": 80, "title": "Customer Success Architect", "apply_url": "x"}]
            _write_json(out_json, ranked)
            out_csv.parent.mkdir(parents=True, exist_ok=True)
            out_csv.write_text("job_id,score\njob-1,80\n", encoding="utf-8")
            _write_json(out_families, [])
            out_md.write_text("# shortlist\n", encoding="utf-8")
            out_top.write_text("# top\n", encoding="utf-8")
            semantic_out.parent.mkdir(parents=True, exist_ok=True)
            if os.environ.get("SEMANTIC_ENABLED") == "1":
                semantic_out.write_text(
                    json.dumps(
                        {
                            "enabled": True,
                            "model_id": "deterministic-hash-v1",
                            "policy": {"max_jobs": 200, "top_k": 50, "max_boost": 5.0, "min_similarity": 0.72},
                            "cache_hit_counts": {"hit": 1, "miss": 0, "write": 0, "profile_hit": 1, "profile_miss": 0},
                            "entries": [
                                {
                                    "provider": "openai",
                                    "profile": "cs",
                                    "job_id": "job-1",
                                    "base_score": 80,
                                    "similarity": 0.8,
                                    "semantic_boost": 1.0,
                                    "final_score": 81,
                                    "reasons": ["boost_applied"],
                                }
                            ],
                            "skipped_reason": None,
                        }
                    ),
                    encoding="utf-8",
                )
            else:
                semantic_out.write_text(
                    json.dumps(
                        {
                            "enabled": False,
                            "model_id": "deterministic-hash-v1",
                            "policy": {"max_jobs": 200, "top_k": 50, "max_boost": 5.0, "min_similarity": 0.72},
                            "cache_hit_counts": {"hit": 0, "miss": 0, "write": 0, "profile_hit": 0, "profile_miss": 0},
                            "entries": [],
                            "skipped_reason": "semantic_disabled",
                        }
                    ),
                    encoding="utf-8",
                )
            return

    monkeypatch.setattr(run_daily, "_run", fake_run)
    monkeypatch.setattr(run_daily, "DATA_DIR", data_dir)
    monkeypatch.setattr(run_daily, "STATE_DIR", state_dir)
    monkeypatch.setattr(run_daily, "RUN_METADATA_DIR", state_dir / "runs")
    monkeypatch.setattr(run_daily, "LAST_RUN_JSON", state_dir / "last_run.json")
    monkeypatch.setattr(run_daily, "LAST_SUCCESS_JSON", state_dir / "last_success.json")
    monkeypatch.setattr(run_daily, "LOCK_PATH", state_dir / "lock")
    monkeypatch.setattr(run_daily, "SNAPSHOT_DIR", snapshot_dir)
    original_archive_input = run_daily._archive_input

    def _archive_input_with_test_state(*args, **kwargs):
        kwargs["state_dir"] = state_dir
        return original_archive_input(*args, **kwargs)

    monkeypatch.setattr(run_daily, "_archive_input", _archive_input_with_test_state)
    run_daily.USE_SUBPROCESS = False

    monkeypatch.setenv("SEMANTIC_ENABLED", "0")
    monkeypatch.setattr(run_daily, "_utcnow_iso", lambda: "2026-01-02T00:00:00Z")
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
    assert run_daily.main() == 0
    assert score_stage_calls == ["score:cs"]
    (state_dir / "lock").unlink(missing_ok=True)

    score_stage_calls.clear()
    non_score_stages.clear()
    monkeypatch.setenv("SEMANTIC_ENABLED", "1")
    monkeypatch.setattr(run_daily, "_utcnow_iso", lambda: "2026-01-03T00:00:00Z")
    assert run_daily.main() == 0
    assert score_stage_calls == ["score:cs"]
    assert "ai_augment" not in non_score_stages

    summary_path = state_dir / "runs" / "20260103T000000Z" / "semantic" / "semantic_summary.json"
    scores_path = state_dir / "runs" / "20260103T000000Z" / "semantic" / "semantic_scores.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    scores = json.loads(scores_path.read_text(encoding="utf-8"))

    assert summary["enabled"] is True
    assert isinstance(summary["cache_hit_counts"], dict)
    assert isinstance(scores, list) and scores
