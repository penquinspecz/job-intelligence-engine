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


def test_compute_match_cs_role_nonzero_when_profile_has_cs_tokens() -> None:
    """
    Ensure CS/business skill labels extracted by rules can produce a non-zero match_score
    when the candidate profile contains the same canonical tokens (string-overlap based).
    """
    ai_payload = ensure_ai_payload(
        {
            "skills_required": ["Adoption", "Onboarding", "Enablement", "Change Management"],
            "skills_preferred": [],
            "role_family": "Customer Success",
            "seniority": "Senior",
        }
    )
    profile = _profile(
        skills={
            "technical_core": [],
            "ai_specific": [],
            "customer_success": ["Adoption", "Onboarding", "Enablement", "Change Management"],
            "domain_knowledge": [],
        },
        target_roles=["customer success"],
        seniority="senior",
    )
    score, notes = compute_match(ai_payload, profile)
    # Required: 4/4 => 70, preferred: 0 => 0, role+seniority bonuses => +10 => 80
    assert score == 80
    assert any("required_match:4/4" in n for n in notes)
    assert any("role_bonus:5" in n for n in notes)
    assert any("seniority_bonus:5" in n for n in notes)


def test_skill_alias_customer_onboarding_design_matches_onboarding() -> None:
    ai_payload = ensure_ai_payload(
        {
            "skills_required": ["Onboarding"],
            "skills_preferred": [],
            "role_family": "",
            "seniority": "IC",
        }
    )
    profile = _profile(
        skills={
            "technical_core": [],
            "ai_specific": [],
            "customer_success": ["Customer onboarding design"],
            "domain_knowledge": [],
        },
        target_roles=[],
        seniority="senior",
    )
    score, notes = compute_match(ai_payload, profile)
    # Required: 1/1 => 70, preferred: 0 => 0, bonuses => 0
    assert score == 70
    assert any("required_match:1/1" in n for n in notes)


def test_skill_alias_training_field_enablement_matches_enablement() -> None:
    ai_payload = ensure_ai_payload(
        {
            "skills_required": ["Enablement"],
            "skills_preferred": [],
            "role_family": "",
            "seniority": "IC",
        }
    )
    profile = _profile(
        skills={
            "technical_core": [],
            "ai_specific": [],
            "customer_success": ["Training & field enablement"],
            "domain_knowledge": [],
        },
        target_roles=[],
        seniority="senior",
    )
    score, notes = compute_match(ai_payload, profile)
    assert score == 70
    assert any("required_match:1/1" in n for n in notes)

