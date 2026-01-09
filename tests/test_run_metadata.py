import json
from pathlib import Path

import scripts.run_daily as run_daily


def test_run_metadata_written_and_deterministic(tmp_path: Path, monkeypatch) -> None:
    telemetry = {
        "status": "success",
        "stages": {"scrape": {"duration_sec": 1.0}},
        "started_at": "2026-01-01T00:00:00Z",
        "ended_at": "2026-01-01T00:05:00Z",
    }
    profiles = ["cs", "tam"]
    flags = {"profile": "cs", "profiles": "cs", "us_only": False, "no_enrich": True, "ai": False, "ai_only": False}
    diff_counts = {"cs": {"new": 1, "changed": 0, "removed": 0}}

    monkeypatch.setattr(run_daily, "RUN_METADATA_DIR", tmp_path)

    path1 = run_daily._persist_run_metadata(
        run_id="2026-01-01T00:00:00Z",
        telemetry=telemetry,
        profiles=profiles,
        flags=flags,
        diff_counts=diff_counts,
    )
    path2 = run_daily._persist_run_metadata(
        run_id="2026-01-01T00:00:00Z",
        telemetry=telemetry,
        profiles=profiles,
        flags=flags,
        diff_counts=diff_counts,
    )

    assert path1 == path2
    data = json.loads(path1.read_text(encoding="utf-8"))
    assert data["run_id"] == "2026-01-01T00:00:00Z"
    assert data["profiles"] == profiles
    assert data["diff_counts"]["cs"]["new"] == 1
    assert data["stage_durations"] == telemetry["stages"]
