from __future__ import annotations

from pathlib import Path

from ji_engine.semantic.boost import SemanticPolicy, apply_bounded_semantic_boost


def _jobs() -> list[dict]:
    return [
        {
            "job_id": "a",
            "title": "Customer Success Architect",
            "location": "Remote",
            "team": "CS",
            "description": "Drive adoption onboarding customer outcomes and renewals",
            "score": 70,
            "final_score": 70,
        },
        {
            "job_id": "b",
            "title": "Customer Success Architect",
            "location": "Remote",
            "team": "CS",
            "description": "Drive adoption onboarding customer outcomes and renewals",
            "score": 69,
            "final_score": 69,
        },
        {
            "job_id": "c",
            "title": "Research Scientist",
            "location": "Remote",
            "team": "AI",
            "description": "Develop novel theoretical models and pretraining",
            "score": 68,
            "final_score": 68,
        },
    ]


def _profile() -> dict:
    return {"summary": "customer success architect adoption onboarding outcomes renewals"}


def test_semantic_disabled_keeps_scores_identical(tmp_path: Path) -> None:
    original = _jobs()
    ranked, evidence = apply_bounded_semantic_boost(
        scored_jobs=original,
        profile_payload=_profile(),
        state_dir=tmp_path / "state",
        policy=SemanticPolicy(enabled=False),
    )
    assert ranked == original
    assert evidence["enabled"] is False
    assert evidence["skipped_reason"] == "semantic_disabled"
    assert evidence["entries"] == []


def test_semantic_boost_is_deterministic_with_stable_rounding(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    policy = SemanticPolicy(enabled=True, top_k=3, max_jobs=3, max_boost=5.0, min_similarity=0.0)

    first_ranked, first = apply_bounded_semantic_boost(
        scored_jobs=_jobs(),
        profile_payload=_profile(),
        state_dir=state_dir,
        policy=policy,
    )
    second_ranked, second = apply_bounded_semantic_boost(
        scored_jobs=_jobs(),
        profile_payload=_profile(),
        state_dir=state_dir,
        policy=policy,
    )

    assert first_ranked == second_ranked
    assert first["entries"] == second["entries"]

    by_job = {item["job_id"]: item for item in first["entries"]}
    assert by_job["c"]["similarity"] == 0.350249
    assert by_job["c"]["semantic_boost"] == 1.751245
    assert by_job["c"]["final_score"] == 70
    assert by_job["c"]["reasons"] == ["boost_applied"]
    assert by_job["a"]["semantic_boost"] == 0.0
    assert by_job["b"]["semantic_boost"] == 0.0

    assert first["cache_hit_counts"]["miss"] == 3
    assert first["cache_hit_counts"]["write"] == 3
    assert second["cache_hit_counts"]["hit"] == 3


def test_semantic_boost_respects_bounds_and_thresholds(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    bounded_policy = SemanticPolicy(enabled=True, top_k=3, max_jobs=3, max_boost=1.0, min_similarity=0.0)
    bounded_ranked, _ = apply_bounded_semantic_boost(
        scored_jobs=_jobs(),
        profile_payload=_profile(),
        state_dir=state_dir,
        policy=bounded_policy,
    )
    for job in bounded_ranked:
        boost = float(job.get("semantic_boost", 0.0) or 0.0)
        assert boost <= 1.0

    threshold_policy = SemanticPolicy(enabled=True, top_k=3, max_jobs=3, max_boost=5.0, min_similarity=0.8)
    threshold_ranked, threshold_evidence = apply_bounded_semantic_boost(
        scored_jobs=_jobs(),
        profile_payload=_profile(),
        state_dir=tmp_path / "state_threshold",
        policy=threshold_policy,
    )
    for job in threshold_ranked:
        assert float(job.get("semantic_boost", 0.0) or 0.0) == 0.0
    for entry in threshold_evidence["entries"]:
        assert float(entry["semantic_boost"]) == 0.0
