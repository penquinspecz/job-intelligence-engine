from __future__ import annotations

import json
from pathlib import Path

from ji_engine.semantic.core import DEFAULT_SEMANTIC_MODEL_ID
from ji_engine.semantic.step import run_semantic_sidecar


def _write_ranked(path: Path, title_suffix: str = "") -> None:
    payload = [
        {
            "job_id": "job-001",
            "title": f"Role One{title_suffix}",
            "location": "Remote",
            "apply_url": "https://example.com/jobs/1",
            "detail_url": "https://example.com/jobs/1",
        },
        {
            "job_id": "job-002",
            "title": "Role Two",
            "location": "NYC",
            "apply_url": "https://example.com/jobs/2",
            "detail_url": "https://example.com/jobs/2",
        },
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _provider_outputs(ranked_path: Path) -> dict:
    return {
        "openai": {
            "cs": {
                "ranked_json": {"path": str(ranked_path)},
            }
        }
    }


def test_semantic_step_disabled_writes_summary(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    run_dir = tmp_path / "runs"
    profile_path = tmp_path / "data" / "candidate_profile.json"
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    profile_path.write_text(json.dumps({"roles": ["cs"]}), encoding="utf-8")
    ranked_path = tmp_path / "data" / "ashby_cache" / "openai_ranked_jobs.cs.json"
    _write_ranked(ranked_path)

    summary, summary_path = run_semantic_sidecar(
        run_id="2026-02-12T00:00:00Z",
        provider_outputs=_provider_outputs(ranked_path),
        state_dir=state_dir,
        run_metadata_dir=run_dir,
        candidate_profile_path=profile_path,
        enabled=False,
        model_id=DEFAULT_SEMANTIC_MODEL_ID,
        max_jobs=200,
    )

    assert summary_path.exists()
    assert summary["enabled"] is False
    assert summary["embedded_job_count"] == 0
    assert summary["skipped_reason"] == "semantic_disabled"


def test_semantic_step_cache_hit_miss_contract(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    run_dir = tmp_path / "runs"
    profile_path = tmp_path / "data" / "candidate_profile.json"
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    profile_path.write_text(json.dumps({"roles": ["cs"], "skills": ["python"]}), encoding="utf-8")
    ranked_path = tmp_path / "data" / "ashby_cache" / "openai_ranked_jobs.cs.json"
    _write_ranked(ranked_path)

    first, _ = run_semantic_sidecar(
        run_id="2026-02-12T00:00:00Z",
        provider_outputs=_provider_outputs(ranked_path),
        state_dir=state_dir,
        run_metadata_dir=run_dir,
        candidate_profile_path=profile_path,
        enabled=True,
        model_id=DEFAULT_SEMANTIC_MODEL_ID,
        max_jobs=200,
    )
    assert first["embedded_job_count"] == 2
    assert first["cache_hit_counts"]["hit"] == 0
    assert first["cache_hit_counts"]["miss"] == 2
    assert first["cache_hit_counts"]["write"] == 2

    second, _ = run_semantic_sidecar(
        run_id="2026-02-12T00:10:00Z",
        provider_outputs=_provider_outputs(ranked_path),
        state_dir=state_dir,
        run_metadata_dir=run_dir,
        candidate_profile_path=profile_path,
        enabled=True,
        model_id=DEFAULT_SEMANTIC_MODEL_ID,
        max_jobs=200,
    )
    assert second["embedded_job_count"] == 2
    assert second["cache_hit_counts"]["hit"] == 2
    assert second["cache_hit_counts"]["miss"] == 0

    # Profile hash change => deterministic cache miss.
    profile_path.write_text(json.dumps({"roles": ["cs"], "skills": ["go"]}), encoding="utf-8")
    profile_changed, _ = run_semantic_sidecar(
        run_id="2026-02-12T00:20:00Z",
        provider_outputs=_provider_outputs(ranked_path),
        state_dir=state_dir,
        run_metadata_dir=run_dir,
        candidate_profile_path=profile_path,
        enabled=True,
        model_id=DEFAULT_SEMANTIC_MODEL_ID,
        max_jobs=200,
    )
    assert profile_changed["cache_hit_counts"]["miss"] == 2

    # Job-content hash change => deterministic cache miss.
    profile_path.write_text(json.dumps({"roles": ["cs"], "skills": ["python"]}), encoding="utf-8")
    _write_ranked(ranked_path, title_suffix=" updated")
    job_changed, summary_path = run_semantic_sidecar(
        run_id="2026-02-12T00:30:00Z",
        provider_outputs=_provider_outputs(ranked_path),
        state_dir=state_dir,
        run_metadata_dir=run_dir,
        candidate_profile_path=profile_path,
        enabled=True,
        model_id=DEFAULT_SEMANTIC_MODEL_ID,
        max_jobs=200,
    )
    assert job_changed["cache_hit_counts"]["miss"] >= 1
    raw_summary = summary_path.read_text(encoding="utf-8")
    assert "Role One" not in raw_summary
    assert "Role Two" not in raw_summary
