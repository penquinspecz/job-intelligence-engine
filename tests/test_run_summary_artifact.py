from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from typing import Any, Dict

from ji_engine.utils.verification import compute_sha256_file
from scripts.schema_validate import resolve_named_schema_path, validate_payload


def _setup_env(monkeypatch: Any, tmp_path: Path) -> Dict[str, Path]:
    data_dir = tmp_path / "data"
    state_dir = tmp_path / "state"
    output_dir = data_dir / "ashby_cache"
    snapshot_dir = data_dir / "openai_snapshots"
    output_dir.mkdir(parents=True, exist_ok=True)
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    state_dir.mkdir(parents=True, exist_ok=True)
    (snapshot_dir / "index.html").write_text("<html>snapshot</html>", encoding="utf-8")
    (data_dir / "candidate_profile.json").write_text('{"skills": [], "roles": []}', encoding="utf-8")
    monkeypatch.setenv("JOBINTEL_DATA_DIR", str(data_dir))
    monkeypatch.setenv("JOBINTEL_STATE_DIR", str(state_dir))
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "")
    return {"data_dir": data_dir, "state_dir": state_dir, "output_dir": output_dir}


def _fake_pipeline_run(run_daily: Any, output_dir: Path, cmd: list[str], *, stage: str) -> None:
    if stage == "scrape":
        (output_dir / "openai_raw_jobs.json").write_text("[]", encoding="utf-8")
        return
    if stage == "classify":
        (output_dir / "openai_labeled_jobs.json").write_text("[]", encoding="utf-8")
        return
    if stage == "enrich":
        (output_dir / "openai_enriched_jobs.json").write_text("[]", encoding="utf-8")
        return
    if stage.startswith("score:"):
        profile = stage.split(":", 1)[1]
        for path in (
            run_daily._provider_ranked_jobs_json("openai", profile),
            run_daily._provider_ranked_jobs_csv("openai", profile),
            run_daily._provider_ranked_families_json("openai", profile),
            run_daily._provider_shortlist_md("openai", profile),
            run_daily._provider_top_md("openai", profile),
        ):
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.suffix == ".json":
                path.write_text("[]", encoding="utf-8")
            else:
                path.write_text("", encoding="utf-8")


def _latest_run_summary(run_daily: Any) -> tuple[Path, Dict[str, Any]]:
    summaries = sorted(run_daily.RUN_METADATA_DIR.glob("*/run_summary.v1.json"))
    assert summaries, "run_summary artifact should exist"
    path = summaries[-1]
    payload = json.loads(path.read_text(encoding="utf-8"))
    return path, payload


def _validate_run_summary_schema(payload: Dict[str, Any]) -> None:
    schema = json.loads(resolve_named_schema_path("run_summary", 1).read_text(encoding="utf-8"))
    errors = validate_payload(payload, schema)
    assert errors == [], f"run_summary schema validation failed: {errors}"


def test_run_summary_written_with_hashes_on_success(tmp_path: Path, monkeypatch: Any) -> None:
    paths = _setup_env(monkeypatch, tmp_path)

    import ji_engine.config as config
    import scripts.run_daily as run_daily

    config = importlib.reload(config)
    run_daily = importlib.reload(run_daily)
    run_daily.USE_SUBPROCESS = False

    monkeypatch.setattr(
        run_daily, "_run", lambda cmd, stage: _fake_pipeline_run(run_daily, paths["output_dir"], cmd, stage=stage)
    )
    monkeypatch.setattr(sys, "argv", ["run_daily.py", "--no_subprocess", "--profiles", "cs", "--no_post"])

    assert run_daily.main() == 0

    summary_path, payload = _latest_run_summary(run_daily)
    _validate_run_summary_schema(payload)

    assert payload["status"] == "success"
    assert payload["run_health"]["status"] == "success"
    assert payload["run_report"]["path"]
    assert payload["scoring_config"]["config_sha256"]

    run_report_path = Path(run_daily.REPO_ROOT / payload["run_report"]["path"])
    assert payload["run_report"]["sha256"] == compute_sha256_file(run_report_path)

    run_health_path = Path(run_daily.REPO_ROOT / payload["run_health"]["path"])
    assert payload["run_health"]["sha256"] == compute_sha256_file(run_health_path)

    costs_path = Path(run_daily.REPO_ROOT / payload["costs"]["path"])
    assert payload["costs"]["sha256"] == compute_sha256_file(costs_path)

    ranked_json = payload["ranked_outputs"]["ranked_json"]
    assert ranked_json
    assert ranked_json[0]["provider"] == "openai"
    assert ranked_json[0]["profile"] == "cs"
    assert ranked_json[0]["sha256"]

    primary = payload["primary_artifacts"]
    assert [item["artifact_key"] for item in primary] == ["ranked_json", "ranked_csv", "shortlist_md"]
    run_dir = payload["quicklinks"]["run_dir"]
    assert isinstance(run_dir, str) and run_dir
    for item in primary:
        assert item["path"].startswith(f"{run_dir}/")
        assert item["sha256"]

    assert payload["quicklinks"]["run_dir"] in summary_path.as_posix()


def test_run_summary_is_pointer_only_and_excludes_raw_profile_text(tmp_path: Path, monkeypatch: Any) -> None:
    paths = _setup_env(monkeypatch, tmp_path)

    import ji_engine.candidates.registry as candidate_registry
    import ji_engine.config as config
    import scripts.run_daily as run_daily

    config = importlib.reload(config)
    candidate_registry = importlib.reload(candidate_registry)
    run_daily = importlib.reload(run_daily)
    run_daily.USE_SUBPROCESS = False

    secret_text = "Authorization: Bearer should-never-appear-in-summary"
    candidate_registry.bootstrap_candidate("local")
    candidate_registry.set_profile_text("local", resume_text=secret_text)

    monkeypatch.setattr(
        run_daily, "_run", lambda cmd, stage: _fake_pipeline_run(run_daily, paths["output_dir"], cmd, stage=stage)
    )
    monkeypatch.setattr(sys, "argv", ["run_daily.py", "--no_subprocess", "--profiles", "cs", "--no_post"])

    assert run_daily.main() == 0

    summary_path, payload = _latest_run_summary(run_daily)
    _validate_run_summary_schema(payload)

    summary_text = summary_path.read_text(encoding="utf-8")
    assert secret_text not in summary_text
    assert "text_input_artifacts" not in summary_text
