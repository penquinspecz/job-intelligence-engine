import json
import os
from datetime import datetime, timezone
from pathlib import Path

import scripts.run_daily as run_daily
from scripts.schema_validate import resolve_schema_path, validate_report


def test_run_metadata_written_and_deterministic(tmp_path: Path, monkeypatch) -> None:
    ts = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc).timestamp()
    monkeypatch.setattr(run_daily, "DATA_DIR", tmp_path)
    output_dir = tmp_path / "ashby_cache"
    output_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(run_daily, "OUTPUT_DIR", output_dir)
    raw_path = output_dir / "openai_raw_jobs.json"
    labeled_path = output_dir / "openai_labeled_jobs.json"
    enriched_path = output_dir / "openai_enriched_jobs.json"
    ai_path = output_dir / "openai_enriched_jobs_ai.json"
    raw_path.write_text('{"raw": true}', encoding="utf-8")
    labeled_path.write_text("[]", encoding="utf-8")
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
    monkeypatch.setenv("JOBINTEL_IMAGE", "unknown")

    def _ranked_json(profile: str) -> Path:
        return output_dir / f"openai_ranked_jobs.{profile}.json"

    def _ranked_csv(profile: str) -> Path:
        return output_dir / f"openai_ranked_jobs.{profile}.csv"

    def _ranked_families(profile: str) -> Path:
        return output_dir / f"openai_ranked_families.{profile}.json"

    def _shortlist(profile: str) -> Path:
        return output_dir / f"openai_shortlist.{profile}.md"

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
    config_fingerprint = run_daily._config_fingerprint(flags, None)
    environment_fingerprint = {
        "python_version": "3.10.14",
        "platform": "test-platform",
        "image_tag": "jobintel:test",
        "git_sha": "deadbeef",
        "tz": "UTC",
        "pythonhashseed": "0",
    }
    scoring_input_selection_by_profile = {
        "cs": {
            "selected": run_daily._file_metadata(enriched_path),
            "selected_path": str(enriched_path),
            "candidate_paths_considered": [
                run_daily._candidate_metadata(ai_path),
                run_daily._candidate_metadata(enriched_path),
                run_daily._candidate_metadata(labeled_path),
            ],
            "selection_reason": "default_enriched_required",
            "selection_reason_labeled_vs_enriched": "enriched_required",
            "selection_reason_enriched_vs_ai": "not_applicable",
            "selection_reason_details": {
                "labeled_vs_enriched": {
                    "rule_id": "labeled_vs_enriched.enriched_required",
                    "chosen_path": str(enriched_path),
                    "candidate_paths": [str(enriched_path), str(labeled_path)],
                    "compared_fields": {
                        "candidates": {
                            str(enriched_path): run_daily._file_metadata(enriched_path),
                            str(labeled_path): run_daily._file_metadata(labeled_path),
                        }
                    },
                    "decision": "enriched_required",
                    "decision_timestamp": "2026-01-01T00:00:00Z",
                },
                "enriched_vs_ai": {
                    "rule_id": "enriched_vs_ai.not_applicable",
                    "chosen_path": None,
                    "candidate_paths": [str(enriched_path), str(ai_path)],
                    "compared_fields": {
                        "candidates": {
                            str(enriched_path): run_daily._file_metadata(enriched_path),
                            str(ai_path): run_daily._file_metadata(ai_path),
                        }
                    },
                    "decision": "not_applicable",
                    "decision_timestamp": "2026-01-01T00:00:00Z",
                },
            },
            "comparison_details": {"newer_by_seconds": 0, "prefer_ai": False},
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
            "selected_path": str(labeled_path),
            "candidate_paths_considered": [
                run_daily._candidate_metadata(ai_path),
                run_daily._candidate_metadata(enriched_path),
                run_daily._candidate_metadata(labeled_path),
            ],
            "selection_reason": "no_enrich_labeled_newer_or_equal",
            "selection_reason_labeled_vs_enriched": "labeled_newer_or_equal",
            "selection_reason_enriched_vs_ai": "not_applicable",
            "selection_reason_details": {
                "labeled_vs_enriched": {
                    "rule_id": "labeled_vs_enriched.labeled_newer_or_equal",
                    "chosen_path": str(labeled_path),
                    "candidate_paths": [str(enriched_path), str(labeled_path)],
                    "compared_fields": {
                        "candidates": {
                            str(enriched_path): run_daily._file_metadata(enriched_path),
                            str(labeled_path): run_daily._file_metadata(labeled_path),
                        },
                        "comparisons": {"winner": "labeled"},
                    },
                    "decision": "labeled_newer_or_equal",
                    "decision_timestamp": "2026-01-01T00:00:00Z",
                },
                "enriched_vs_ai": {
                    "rule_id": "enriched_vs_ai.not_applicable",
                    "chosen_path": None,
                    "candidate_paths": [str(enriched_path), str(ai_path)],
                    "compared_fields": {
                        "candidates": {
                            str(enriched_path): run_daily._file_metadata(enriched_path),
                            str(ai_path): run_daily._file_metadata(ai_path),
                        }
                    },
                    "decision": "not_applicable",
                    "decision_timestamp": "2026-01-01T00:00:00Z",
                },
            },
            "comparison_details": {"newer_by_seconds": 0, "prefer_ai": False},
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
        config_fingerprint=config_fingerprint,
        environment_fingerprint=environment_fingerprint,
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
        config_fingerprint=config_fingerprint,
        environment_fingerprint=environment_fingerprint,
    )

    assert path1 == path2
    data = json.loads(path1.read_text(encoding="utf-8"))
    assert data["run_id"] == "2026-01-01T00:00:00Z"
    assert data["profiles"] == profiles
    assert data["providers"] == ["openai"]
    assert data["diff_counts"]["cs"]["new"] == 1
    assert data["stage_durations"] == telemetry["stages"]
    assert data["run_report_schema_version"] == 1
    assert data["git_sha"] == "deadbeef"
    assert data["image_tag"] == "jobintel:test"
    assert data["inputs"]["raw_jobs_json"]["path"] == str(raw_path)
    assert data["inputs"]["ai_enriched_jobs_json"]["path"] == str(ai_path)
    assert data["inputs_by_provider"]["openai"]["raw_jobs_json"]["path"] == str(raw_path)
    assert data["scoring_inputs_by_profile"]["cs"]["path"] == str(enriched_path)
    assert data["scoring_inputs_by_provider"]["openai"]["cs"]["path"] == str(enriched_path)
    assert data["outputs_by_profile"]["tam"]["ranked_csv"]["path"] == str(_ranked_csv("tam"))
    assert data["outputs_by_provider"]["openai"]["tam"]["ranked_csv"]["path"] == str(_ranked_csv("tam"))
    assert data["config_fingerprint"] == config_fingerprint
    assert len(data["config_fingerprint"]) == 64
    assert all(ch in "0123456789abcdef" for ch in data["config_fingerprint"])
    assert data["environment_fingerprint"]["python_version"] == "3.10.14"
    assert data["environment_fingerprint"]["platform"] == "test-platform"
    assert data["environment_fingerprint"]["tz"] == "UTC"
    assert data["environment_fingerprint"]["pythonhashseed"] == "0"
    verifiable = data["verifiable_artifacts"]
    assert isinstance(verifiable, dict)
    for profile in profiles:
        for key in ("ranked_json", "ranked_csv", "ranked_families_json", "shortlist_md"):
            logical_key = f"openai:{profile}:{key}"
            assert logical_key in verifiable
            expected_meta = data["outputs_by_provider"]["openai"][profile][key]
            expected_sha = expected_meta["sha256"]
            expected_path = Path(expected_meta["path"]).relative_to(run_daily.DATA_DIR).as_posix()
            assert verifiable[logical_key]["sha256"] == expected_sha
            assert verifiable[logical_key]["hash_algo"] == "sha256"
            assert verifiable[logical_key]["path"] == expected_path
            assert verifiable[logical_key]["bytes"] == Path(expected_meta["path"]).stat().st_size
    assert data["scoring_input_selection_by_profile"]["cs"]["decision"]["rule"] == "default_enriched_required"
    assert data["scoring_input_selection_by_profile"]["tam"]["decision"]["rule"] == "no_enrich_compare"
    assert (
        data["scoring_input_selection_by_provider"]["openai"]["cs"]["decision"]["rule"] == "default_enriched_required"
    )
    assert (
        data["scoring_input_selection_by_profile"]["cs"]["selection_reason_details"]["labeled_vs_enriched"]["rule_id"]
        == "labeled_vs_enriched.enriched_required"
    )
    assert data["scoring_input_selection_by_profile"]["cs"]["selection_reason_details"]["labeled_vs_enriched"][
        "chosen_path"
    ] == str(enriched_path)
    assert (
        data["scoring_input_selection_by_profile"]["tam"]["selection_reason_details"]["labeled_vs_enriched"]["rule_id"]
        == "labeled_vs_enriched.labeled_newer_or_equal"
    )
    assert data["scoring_input_selection_by_profile"]["tam"]["selection_reason_details"]["labeled_vs_enriched"][
        "chosen_path"
    ] == str(labeled_path)
    assert data["provenance"]["build"]["git_sha"] == "unknown"
    assert data["provenance"]["build"]["image"] == "unknown"
    assert data["provenance"]["build"]["taskdef"] == "unknown"
    assert data["provenance"]["build"]["ecs_task_arn"] == "unknown"
    assert data["ai_accounting"]["totals"]["calls"] == 0
    assert data["ai_accounting"]["totals"]["tokens_total"] == 0
    assert data["ai_accounting"]["totals"]["estimated_cost_usd"] == "0.000000"
    assert data["candidate_input_provenance"]["candidate_id"] == run_daily.CANDIDATE_ID
    assert data["candidate_input_provenance"]["text_input_artifacts"] == {}
    assert data["provenance"]["candidate_inputs"]["text_input_artifacts"] == {}
    assert path1.name == "20260101T000000Z.json"
    schema = json.loads(resolve_schema_path(1).read_text(encoding="utf-8"))
    assert validate_report(data, schema) == []


def test_config_fingerprint_ignores_env_secrets(monkeypatch) -> None:
    flags = {
        "profile": "cs",
        "profiles": "cs",
        "providers": ["openai"],
        "us_only": False,
        "no_enrich": False,
        "ai": False,
        "ai_only": False,
        "min_score": 40,
        "min_alert_score": 85,
    }
    base = run_daily._config_fingerprint(flags, None)
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://example.com/secret")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-secret")
    again = run_daily._config_fingerprint(flags, None)
    assert base == again
