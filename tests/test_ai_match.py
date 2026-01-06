from __future__ import annotations

from ji_engine.ai.match import compute_match
from ji_engine.ai.schema import ensure_ai_payload


def _profile(skills=None, target_roles=None, seniority="senior"):
    return {
        "skills": skills
        or {
            "technical_core": ["Python", "SQL", "APIs"],
            "ai_specific": ["ML", "NLP"],
            "customer_success": [],
            "domain_knowledge": ["Fintech"],
        },
        "preferences": {
            "target_roles": target_roles or ["ml engineer"],
            "target_locations": [],
            "target_companies": [],
            "anti_patterns": [],
            "seniority_level": seniority,
        },
    }


def test_compute_match_scores_required_and_preferred():
    ai_payload = ensure_ai_payload(
        {
            "skills_required": ["Python", "ML"],
            "skills_preferred": ["Fintech"],
            "role_family": "ML Engineer",
            "seniority": "Senior",
        }
    )
    score, notes = compute_match(ai_payload, _profile())
    assert isinstance(score, int)
    assert 0 <= score <= 100
    # Required: 2/2 (70), Preferred: 1/1 (20), role + seniority bonuses (10) => 100 capped
    assert score == 100
    assert any("required_match:2/2" in n for n in notes)
    assert any("preferred_match:1/1" in n for n in notes)


def test_compute_match_handles_partial_and_caps():
    ai_payload = ensure_ai_payload(
        {
            "skills_required": ["Go", "Rust"],
            "skills_preferred": ["Python"],
            "role_family": "Backend",
            "seniority": "Mid",
        }
    )
    score, notes = compute_match(ai_payload, _profile())
    assert isinstance(score, int)
    assert 0 <= score <= 100
    # Required: 0/2 => 0, Preferred: 1/1 => 20, bonuses likely 0 => total 20
    assert score == 20
    assert any("required_match:0/2" in n for n in notes)

