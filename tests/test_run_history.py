import importlib
import hashlib
from pathlib import Path

import ji_engine.config as config
import scripts.run_daily as run_daily


def _write(tmp_path: Path, name: str) -> Path:
    path = tmp_path / name
    data = f"{name}-{hashlib.sha1(name.encode()).hexdigest()}"
    path.write_text(data, encoding="utf-8")
    return path


def test_history_paths_and_latest(tmp_path: Path, monkeypatch) -> None:
    history_base = tmp_path / "state" / "history"
    monkeypatch.setattr(run_daily, "HISTORY_DIR", history_base)

    run_id = "2026-01-01T00:00:00.000000+00:00"
    profile = "cs"
    dataset = {
        "ranked_json": _write(tmp_path, "ranked.json"),
        "ranked_csv": _write(tmp_path, "ranked.csv"),
        "families": _write(tmp_path, "families.json"),
        "shortlist": _write(tmp_path, "shortlist.md"),
        "metadata": _write(tmp_path, "run_meta.json"),
    }

    monkeypatch.setattr(run_daily, "ranked_jobs_json", lambda p: dataset["ranked_json"])
    monkeypatch.setattr(run_daily, "ranked_jobs_csv", lambda p: dataset["ranked_csv"])
    monkeypatch.setattr(run_daily, "ranked_families_json", lambda p: dataset["families"])
    monkeypatch.setattr(run_daily, "shortlist_md_path", lambda p: dataset["shortlist"])

    summary_payload = {
        "run_id": run_id,
        "timestamp": "2026-01-01T00:00:00Z",
        "profile": profile,
        "flags": {},
        "short_circuit": False,
        "diff_counts": {"new": 0, "changed": 0, "removed": 0},
    }
    run_daily._archive_profile_artifacts(run_id, profile, dataset["metadata"], summary_payload)

    history_dir = run_daily._history_run_dir(run_id, profile)
    latest_dir = run_daily._latest_profile_dir(profile)

    for key, src in dataset.items():
        assert (history_dir / src.name).read_text(encoding="utf-8") == src.read_text(
            encoding="utf-8"
        )
        if key != "metadata":
            assert (latest_dir / src.name).read_text(encoding="utf-8") == src.read_text(
                encoding="utf-8"
            )
    run_meta_name = dataset["metadata"].name
    assert (history_dir / run_meta_name).exists()
    assert (latest_dir / "run_metadata.json").exists()
    assert not any(p.name == run_meta_name for p in latest_dir.iterdir())


def test_short_circuit_history_summary(tmp_path: Path, monkeypatch) -> None:
    history_base = tmp_path / "state" / "history"
    runs_dir = tmp_path / "state" / "runs"
    monkeypatch.setattr(run_daily, "HISTORY_DIR", history_base)
    monkeypatch.setattr(run_daily, "RUN_METADATA_DIR", runs_dir)

    run_id = "2026-01-03T00:00:00Z"
    profile = "cs"
    telemetry = {"status": "short_circuit", "stages": {}}
    metadata = run_daily._persist_run_metadata(
        run_id,
        telemetry,
        [profile],
        {"profile": "cs", "profiles": "", "us_only": False, "no_enrich": False, "ai": False, "ai_only": False},
        {profile: {"new": 0, "changed": 0, "removed": 0}},
        {profile: {"path": None, "mtime_iso": None, "sha256": None}},
        {profile: {"selected": None, "candidates": [], "decision": {"rule": "default_enriched_required", "flags": {}, "comparisons": {}, "reason": ""}}},
    )

    summary_payload = {
        "run_id": run_id,
        "timestamp": "2026-01-03T00:00:00Z",
        "profile": profile,
        "flags": {"profile": profile},
        "short_circuit": True,
        "diff_counts": {"new": 0, "changed": 0, "removed": 0},
    }
    run_daily._archive_profile_artifacts(run_id, profile, metadata, summary_payload)
    summary = run_daily._history_run_dir(run_id, profile) / "run_summary.txt"
    assert summary.exists()
    assert "short_circuit" in summary.read_text(encoding="utf-8")


def test_short_circuit_history_dir(tmp_path: Path, monkeypatch):
    override = tmp_path / "custom_state"
    monkeypatch.setenv("JOBINTEL_STATE_DIR", str(override))
    import importlib

    import ji_engine.config as config

    importlib.reload(config)
    importlib.reload(run_daily)

    run_id = "2026-01-04T00:00:00Z"
    profile = "cs"
    telemetry = {"status": "short_circuit", "stages": {}, "ended_at": "2026-01-04T00:00:00Z"}
    metadata = run_daily._persist_run_metadata(
        run_id,
        telemetry,
        [profile],
        {"profile": profile, "profiles": "", "us_only": False, "no_enrich": False, "ai": False, "ai_only": False},
        {profile: {"new": 0, "changed": 0, "removed": 0}},
        {profile: {"path": None, "mtime_iso": None, "sha256": None}},
        {profile: {"selected": None, "candidates": [], "decision": {"rule": "default_enriched_required", "flags": {}, "comparisons": {}, "reason": ""}}},
    )

    summary_payload = {
        "run_id": run_id,
        "timestamp": telemetry["ended_at"],
        "profile": profile,
        "flags": {"profile": profile},
        "short_circuit": True,
        "diff_counts": {"new": 0, "changed": 0, "removed": 0},
    }

    run_daily._archive_profile_artifacts(run_id, profile, metadata, summary_payload)

    history_summary = override / "history" / "2026-01-04" / "20260104T000000Z" / profile / "run_summary.txt"
    latest_summary = override / "history" / "latest" / profile / "run_summary.txt"
    assert history_summary.exists()
    assert latest_summary.exists()
    assert "short_circuit" in history_summary.read_text()
