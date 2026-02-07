from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import scripts.run_daily as run_daily
from ji_engine.history_retention import update_history_retention, write_history_run_artifacts


def _mk_run_dir(runs_root: Path, run_id: str) -> Path:
    run_dir = runs_root / run_id.replace(":", "").replace("-", "").replace(".", "")
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run_report.json").write_text('{"ok": true}\n', encoding="utf-8")
    return run_dir


def _mk_run_report_with_ranked(runs_root: Path, run_id: str, provider: str, profile: str) -> Path:
    run_dir = runs_root / run_id.replace(":", "").replace("-", "").replace(".", "")
    run_dir.mkdir(parents=True, exist_ok=True)
    ranked_path = runs_root.parent / "data" / f"{provider}_ranked_jobs.{profile}.json"
    ranked_path.parent.mkdir(parents=True, exist_ok=True)
    ranked_path.write_text(
        json.dumps(
            [
                {
                    "job_id": "job-1",
                    "title": "Software Engineer",
                    "location": "San Francisco, CA",
                    "team": "Platform",
                    "apply_url": "https://jobs.example.com/role-1?utm_source=x",
                    "jd_hash": "hash-1",
                },
                {
                    "job_id": "job-2",
                    "title": "ML Engineer",
                    "location": "Remote",
                    "team": "Applied AI",
                    "apply_url": "https://jobs.example.com/role-2",
                    "jd_hash": "hash-2",
                },
            ],
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    report = {
        "run_id": run_id,
        "run_report_schema_version": 1,
        "providers": [provider],
        "flags": {
            "offline": True,
            "snapshot_only": True,
            "no_enrich": False,
            "ai": False,
            "ai_only": False,
            "us_only": True,
            "min_score": 40,
        },
        "outputs_by_provider": {
            provider: {
                profile: {
                    "ranked_json": {"path": str(ranked_path)},
                }
            }
        },
        "provenance_by_provider": {
            provider: {
                "scrape_mode": "snapshot",
                "snapshot_used": True,
                "parsed_job_count": 2,
                "live_attempted": False,
                "live_result": "skipped",
                "policy_snapshot": {"rate_limit_config": {"min_delay_s": 1.0}},
                "robots_final_allowed": True,
            }
        },
    }
    report_path = run_dir / "run_report.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report_path


def test_history_retention_prunes_pointers_only(tmp_path: Path) -> None:
    history_root = tmp_path / "state" / "history"
    runs_root = tmp_path / "state" / "runs"
    profile = "cs"
    existing_runs = [
        "2026-01-01T00:00:00Z",
        "2026-01-02T00:00:00Z",
        "2026-01-03T00:00:00Z",
    ]
    for run_id in existing_runs:
        _mk_run_dir(runs_root, run_id)
        update_history_retention(
            history_dir=history_root,
            runs_dir=runs_root,
            profile=profile,
            run_id=run_id,
            run_timestamp=f"{run_id[:10]}T00:00:00Z",
            keep_runs=10,
            keep_days=10,
            written_at="2026-01-04T00:00:00Z",
        )

    newest = "2026-01-04T00:00:00Z"
    _mk_run_dir(runs_root, newest)
    result = update_history_retention(
        history_dir=history_root,
        runs_dir=runs_root,
        profile=profile,
        run_id=newest,
        run_timestamp="2026-01-04T00:00:00Z",
        keep_runs=2,
        keep_days=2,
        written_at="2026-01-04T00:00:00Z",
    )

    assert result.runs_kept == 2
    assert result.runs_pruned == 2
    assert result.daily_kept == 2
    assert result.daily_pruned == 2

    run_pointer_dir = history_root / profile / "runs"
    kept_run_ids = sorted(p.name for p in run_pointer_dir.iterdir() if p.is_dir())
    assert kept_run_ids == ["2026-01-03T00:00:00Z", "2026-01-04T00:00:00Z"]

    daily_dir = history_root / profile / "daily"
    kept_days = sorted(p.name for p in daily_dir.iterdir() if p.is_dir())
    assert kept_days == ["2026-01-03", "2026-01-04"]

    # Retention must never delete run registry data by default.
    all_runs_still_exist = sorted(p.name for p in runs_root.iterdir() if p.is_dir())
    assert len(all_runs_still_exist) == 4


def test_history_retention_is_deterministic_for_fixed_inputs(tmp_path: Path) -> None:
    history_root = tmp_path / "state" / "history"
    runs_root = tmp_path / "state" / "runs"
    profile = "tam"
    run_id = "2026-02-07T12:34:56Z"
    _mk_run_dir(runs_root, run_id)

    first = update_history_retention(
        history_dir=history_root,
        runs_dir=runs_root,
        profile=profile,
        run_id=run_id,
        run_timestamp="2026-02-07T12:34:56Z",
        keep_runs=30,
        keep_days=90,
        written_at="2026-02-07T12:35:00Z",
    )
    second = update_history_retention(
        history_dir=history_root,
        runs_dir=runs_root,
        profile=profile,
        run_id=run_id,
        run_timestamp="2026-02-07T12:34:56Z",
        keep_runs=30,
        keep_days=90,
        written_at="2026-02-07T12:35:00Z",
    )
    assert first == second

    run_pointer = history_root / profile / "runs" / run_id / "pointer.json"
    daily_pointer = history_root / profile / "daily" / "2026-02-07" / "pointer.json"
    retention = history_root / profile / "retention.json"

    run_payload = json.loads(run_pointer.read_text(encoding="utf-8"))
    daily_payload = json.loads(daily_pointer.read_text(encoding="utf-8"))
    retention_payload = json.loads(retention.read_text(encoding="utf-8"))

    assert run_payload["run_id"] == run_id
    assert daily_payload["run_id"] == run_id
    assert retention_payload == {
        "keep_days": 90,
        "keep_runs": 30,
        "profile": profile,
        "schema_version": 1,
        "updated_at": "2026-02-07T12:35:00Z",
    }


def test_history_settings_defaults_safe(monkeypatch) -> None:
    monkeypatch.delenv("HISTORY_ENABLED", raising=False)
    monkeypatch.delenv("HISTORY_KEEP_RUNS", raising=False)
    monkeypatch.delenv("HISTORY_KEEP_DAYS", raising=False)
    enabled, keep_runs, keep_days = run_daily._resolve_history_settings(
        SimpleNamespace(history_enabled=False, history_keep_runs=None, history_keep_days=None)
    )
    assert enabled is False
    assert keep_runs == 30
    assert keep_days == 90


def test_write_history_run_artifacts_is_deterministic(tmp_path: Path) -> None:
    history_root = tmp_path / "state" / "history"
    runs_root = tmp_path / "state" / "runs"
    run_id = "2026-02-07T12:34:56Z"
    profile = "cs"
    report_path = _mk_run_report_with_ranked(runs_root, run_id, "openai", profile)

    first = write_history_run_artifacts(
        history_dir=history_root,
        run_id=run_id,
        profile=profile,
        run_report_path=report_path,
        written_at="2026-02-07T12:35:00Z",
    )
    second = write_history_run_artifacts(
        history_dir=history_root,
        run_id=run_id,
        profile=profile,
        run_report_path=report_path,
        written_at="2026-02-07T12:35:00Z",
    )
    assert first == second

    identity_path = history_root / profile / "runs" / run_id / "identity_map.json"
    provenance_path = history_root / profile / "runs" / run_id / "provenance.json"
    assert identity_path.exists()
    assert provenance_path.exists()

    identity_payload = json.loads(identity_path.read_text(encoding="utf-8"))
    assert identity_payload["schema_version"] == 1
    assert identity_payload["run_id"] == run_id
    assert identity_payload["profile"] == profile
    assert identity_payload["identity_count"] == 2
    assert sorted(identity_payload["identities_by_job_id"].keys()) == ["job-1", "job-2"]
    assert identity_payload["identities_by_job_id"]["job-1"]["normalized_url"] == "https://jobs.example.com/role-1"

    provenance_payload = json.loads(provenance_path.read_text(encoding="utf-8"))
    assert provenance_payload["schema_version"] == 1
    assert provenance_payload["run_report_schema_version"] == 1
    assert provenance_payload["selection_scrape_provenance"]["openai"]["scrape_mode"] == "snapshot"
    assert provenance_payload["flags"]["snapshot_only"] is True


def test_retention_prunes_identity_and_provenance_with_old_pointers(tmp_path: Path) -> None:
    history_root = tmp_path / "state" / "history"
    runs_root = tmp_path / "state" / "runs"
    profile = "cs"
    run_ids = [
        "2026-01-01T00:00:00Z",
        "2026-01-02T00:00:00Z",
        "2026-01-03T00:00:00Z",
    ]
    for run_id in run_ids:
        report_path = _mk_run_report_with_ranked(runs_root, run_id, "openai", profile)
        write_history_run_artifacts(
            history_dir=history_root,
            run_id=run_id,
            profile=profile,
            run_report_path=report_path,
            written_at="2026-01-04T00:00:00Z",
        )
        update_history_retention(
            history_dir=history_root,
            runs_dir=runs_root,
            profile=profile,
            run_id=run_id,
            run_timestamp=f"{run_id[:10]}T00:00:00Z",
            keep_runs=2,
            keep_days=2,
            written_at="2026-01-04T00:00:00Z",
        )

    kept_dir = history_root / profile / "runs"
    kept = sorted(path.name for path in kept_dir.iterdir() if path.is_dir())
    assert kept == ["2026-01-02T00:00:00Z", "2026-01-03T00:00:00Z"]
    assert not (kept_dir / "2026-01-01T00:00:00Z").exists()
    assert (kept_dir / "2026-01-02T00:00:00Z" / "identity_map.json").exists()
    assert (kept_dir / "2026-01-03T00:00:00Z" / "provenance.json").exists()
