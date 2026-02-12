from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import scripts.run_daily as run_daily_module


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def test_m7_semantic_proof_receipt_offline(tmp_path: Path, monkeypatch) -> None:
    data_dir = tmp_path / "data"
    state_dir = tmp_path / "state"
    output_dir = data_dir / "ashby_cache"
    output_dir.mkdir(parents=True, exist_ok=True)
    state_dir.mkdir(parents=True, exist_ok=True)

    fixture_jobs = json.loads(
        (Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "m7" / "semantic_proof_labeled.json").read_text(
            encoding="utf-8"
        )
    )
    _write_json(
        data_dir / "candidate_profile.json",
        {"summary": "customer success architect adoption onboarding outcomes renewals"},
    )
    snapshot_dir = data_dir / "openai_snapshots"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    snapshot_fixture = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "openai_index_with_apply.html"
    (snapshot_dir / "index.html").write_text(snapshot_fixture.read_text(encoding="utf-8"), encoding="utf-8")
    providers_config = tmp_path / "providers.json"
    _write_json(
        providers_config,
        {
            "schema_version": 1,
            "providers": [
                {
                    "provider_id": "openai",
                    "display_name": "OpenAI",
                    "careers_urls": ["https://jobs.ashbyhq.com/openai"],
                    "allowed_domains": ["jobs.ashbyhq.com"],
                    "extraction_mode": "ashby",
                    "mode": "snapshot",
                    "snapshot_path": str(snapshot_dir / "index.html"),
                    "enabled": True,
                }
            ],
        },
    )

    monkeypatch.setenv("JOBINTEL_DATA_DIR", str(data_dir))
    monkeypatch.setenv("JOBINTEL_STATE_DIR", str(state_dir))
    monkeypatch.setenv("JOBINTEL_OUTPUT_DIR", str(output_dir))
    monkeypatch.setenv("SEMANTIC_ENABLED", "1")
    monkeypatch.setenv("SEMANTIC_MODEL_ID", "deterministic-hash-v1")
    monkeypatch.setenv("SEMANTIC_TOP_K", "3")
    monkeypatch.setenv("SEMANTIC_MAX_JOBS", "10")
    monkeypatch.setenv("SEMANTIC_MIN_SIMILARITY", "0.0")
    monkeypatch.setenv("JOBINTEL_RUN_ID", "m7-proof-2026-02-12")

    run_daily = importlib.reload(run_daily_module)
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

    def fake_run(cmd: list[str], *, stage: str) -> None:
        if stage == "scrape":
            _write_json(output_dir / "openai_raw_jobs.json", fixture_jobs)
            _write_json(
                output_dir / "openai_scrape_meta.json",
                {"provider": "openai", "scrape_mode": "snapshot", "parsed_job_count": len(fixture_jobs)},
            )
            return
        if stage == "classify":
            _write_json(output_dir / "openai_labeled_jobs.json", fixture_jobs)
            return
        if stage.startswith("score:"):
            import scripts.score_jobs as score_jobs

            old_argv = sys.argv
            sys.argv = [Path(cmd[1]).name, *cmd[2:]]
            try:
                rc = score_jobs.main()
            finally:
                sys.argv = old_argv
            if rc not in (None, 0):
                raise RuntimeError(f"score_jobs failed with rc={rc}")
            return
        raise RuntimeError(f"unexpected stage in proof test: {stage}")

    monkeypatch.setattr(run_daily, "_run", fake_run)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_daily.py",
            "--no_subprocess",
            "--providers",
            "openai",
            "--providers-config",
            str(providers_config),
            "--profiles",
            "cs",
            "--offline",
            "--no_enrich",
            "--no_post",
        ],
    )

    rc = run_daily.main()
    assert rc == 0

    run_dir = state_dir / "runs" / "m7proof20260212"
    run_report = json.loads((run_dir / "run_report.json").read_text(encoding="utf-8"))
    assert run_report["run_id"] == "m7-proof-2026-02-12"

    summary_path = run_dir / "semantic" / "semantic_summary.json"
    scores_path = run_dir / "semantic" / "semantic_scores.json"
    assert summary_path.exists()
    assert scores_path.exists()

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    scores = json.loads(scores_path.read_text(encoding="utf-8"))

    assert isinstance(summary.get("cache_hit_counts"), dict)
    assert summary["embedded_job_count"] == len(scores)
    assert isinstance(scores, list) and scores
    assert any(isinstance(entry.get("similarity"), float) for entry in scores)
    assert any(float(entry.get("semantic_boost", 0.0) or 0.0) > 0.0 for entry in scores)

    for entry in scores:
        base = int(entry["base_score"])
        boost = float(entry["semantic_boost"])
        expected = max(0, min(100, int(round(base + boost))))
        assert int(entry["final_score"]) == expected
