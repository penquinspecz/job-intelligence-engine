import json
import os
from datetime import datetime, timezone
from pathlib import Path

import scripts.run_daily as run_daily


def test_run_metadata_written_and_deterministic(tmp_path: Path, monkeypatch) -> None:
    ts = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc).timestamp()
    raw_path = tmp_path / "openai_raw_jobs.json"
    labeled_path = tmp_path / "openai_labeled_jobs.json"
    enriched_path = tmp_path / "openai_enriched_jobs.json"
    ai_path = tmp_path / "openai_enriched_jobs_ai.json"
    raw_path.write_text('{"raw": true}', encoding="utf-8")
    labeled_path.write_text('{"labeled": true}', encoding="utf-8")
    enriched_path.write_text('{"enriched": true}', encoding="utf-8")
    ai_path.write_text('{"ai": true}', encoding="utf-8")
    os.utime(raw_path, (ts, ts))
    os.utime(labeled_path, (ts, ts))
    os.utime(enriched_path, (ts, ts))
    os.utime(ai_path, (ts, ts))

    monkeypatch.setattr(run_daily, "RAW_JOBS_JSON", raw_path)
    monkeypatch.setattr(run_daily, "LABELED_JOBS_JSON", labeled_path)
    monkeypatch.setattr(run_daily, "ENRICHED_JOBS_JSON", enriched_path)

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
    monkeypatch.setenv("GIT_SHA", "deadbeef")
    monkeypatch.setenv("IMAGE_TAG", "jobintel:test")

    def _ranked_json(profile: str) -> Path:
        return tmp_path / f"ranked.{profile}.json"

    def _ranked_csv(profile: str) -> Path:
        return tmp_path / f"ranked.{profile}.csv"

    def _ranked_families(profile: str) -> Path:
        return tmp_path / f"ranked_families.{profile}.json"

    def _shortlist(profile: str) -> Path:
        return tmp_path / f"shortlist.{profile}.md"

    monkeypatch.setattr(run_daily, "ranked_jobs_json", _ranked_json)
    monkeypatch.setattr(run_daily, "ranked_jobs_csv", _ranked_csv)
    monkeypatch.setattr(run_daily, "ranked_families_json", _ranked_families)
    monkeypatch.setattr(run_daily, "shortlist_md_path", _shortlist)

    for profile in profiles:
        _ranked_json(profile).write_text(f'{{"{profile}": "json"}}', encoding="utf-8")
        _ranked_csv(profile).write_text(f"{profile},csv\n", encoding="utf-8")
        _ranked_families(profile).write_text(f'{{"{profile}": "families"}}', encoding="utf-8")
        _shortlist(profile).write_text(f"# {profile}\n", encoding="utf-8")
        os.utime(_ranked_json(profile), (ts, ts))
        os.utime(_ranked_csv(profile), (ts, ts))
        os.utime(_ranked_families(profile), (ts, ts))
        os.utime(_shortlist(profile), (ts, ts))

    scoring_inputs_by_profile = {
        "cs": run_daily._file_metadata(enriched_path),
        "tam": run_daily._file_metadata(labeled_path),
    }
    scoring_input_selection_by_profile = {
        "cs": {
            "selected": run_daily._file_metadata(enriched_path),
            "candidates": [
                run_daily._candidate_metadata(ai_path),
                run_daily._candidate_metadata(enriched_path),
                run_daily._candidate_metadata(labeled_path),
            ],
            "decision": {
                "rule": "default_enriched_required",
                "flags": {"no_enrich": False, "ai": False, "ai_only": False},
                "comparisons": {},
                "reason": "default requires enriched input",
            },
        },
        "tam": {
            "selected": run_daily._file_metadata(labeled_path),
            "candidates": [
                run_daily._candidate_metadata(ai_path),
                run_daily._candidate_metadata(enriched_path),
                run_daily._candidate_metadata(labeled_path),
            ],
            "decision": {
                "rule": "no_enrich_compare",
                "flags": {"no_enrich": True, "ai": False, "ai_only": False},
                "comparisons": {
                    "enriched_mtime": ts,
                    "labeled_mtime": ts,
                    "winner": "labeled",
                },
                "reason": "labeled newer or same mtime as enriched",
            },
        },
    }

    path1 = run_daily._persist_run_metadata(
        run_id="2026-01-01T00:00:00Z",
        telemetry=telemetry,
        profiles=profiles,
        flags=flags,
        diff_counts=diff_counts,
        provenance_by_provider=None,
        scoring_inputs_by_profile=scoring_inputs_by_profile,
        scoring_input_selection_by_profile=scoring_input_selection_by_profile,
    )
    path2 = run_daily._persist_run_metadata(
        run_id="2026-01-01T00:00:00Z",
        telemetry=telemetry,
        profiles=profiles,
        flags=flags,
        diff_counts=diff_counts,
        provenance_by_provider=None,
        scoring_inputs_by_profile=scoring_inputs_by_profile,
        scoring_input_selection_by_profile=scoring_input_selection_by_profile,
    )

    assert path1 == path2
    data = json.loads(path1.read_text(encoding="utf-8"))
    assert data["run_id"] == "2026-01-01T00:00:00Z"
    assert data["profiles"] == profiles
    assert data["providers"] == ["openai"]
    assert data["diff_counts"]["cs"]["new"] == 1
    assert data["stage_durations"] == telemetry["stages"]
    assert data["run_report_schema_version"] == "1"
    assert data["git_sha"] == "deadbeef"
    assert data["image_tag"] == "jobintel:test"
    assert data["inputs"]["raw_jobs_json"]["path"] == str(raw_path)
    assert data["inputs"]["ai_enriched_jobs_json"]["path"] == str(ai_path)
    assert data["inputs_by_provider"]["openai"]["raw_jobs_json"]["path"] == str(raw_path)
    assert data["scoring_inputs_by_profile"]["cs"]["path"] == str(enriched_path)
    assert data["scoring_inputs_by_provider"]["openai"]["cs"]["path"] == str(enriched_path)
    assert data["outputs_by_profile"]["tam"]["ranked_csv"]["path"] == str(_ranked_csv("tam"))
    assert data["outputs_by_provider"]["openai"]["tam"]["ranked_csv"]["path"] == str(_ranked_csv("tam"))
    assert data["scoring_input_selection_by_profile"]["cs"]["decision"]["rule"] == "default_enriched_required"
    assert data["scoring_input_selection_by_profile"]["tam"]["decision"]["rule"] == "no_enrich_compare"
    assert data["scoring_input_selection_by_provider"]["openai"]["cs"]["decision"]["rule"] == "default_enriched_required"
    assert path1.name == "20260101T000000Z.json"
