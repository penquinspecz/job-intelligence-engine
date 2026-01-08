from __future__ import annotations

import json
from pathlib import Path

from ji_engine.ai.extract_rules import extract_ai_fields
from ji_engine.ai.match import compute_match


def test_invariant_solutions_architect_title_wins_unless_forward_deployed() -> None:
    # Any title containing "Solutions Architect" should map to role_family=Solutions Architect...
    for title in [
        "Solutions Architect, Generative AI Deployment",
        "Partner Solutions Architect",
        "Solutions Architect, Gov",
        "Senior Solutions Architect",
    ]:
        out = extract_ai_fields({"title": title, "jd_text": "AI deployment and adoption. Customer success."})
        assert out["role_family"] == "Solutions Architect"

    # ...unless the title explicitly contains "Forward Deployed".
    out = extract_ai_fields({"title": "Forward Deployed Solutions Architect", "jd_text": "AI deployment."})
    assert out["role_family"] == "Forward Deployed"


def test_invariant_solutions_engineer_title_maps_to_solutions_architect() -> None:
    out = extract_ai_fields(
        {
            "title": "Solutions Engineer, Public Sector",
            "jd_text": "Partner with Product to shape roadmap and launch features.",
        }
    )
    assert out["role_family"] != "Product"
    assert out["role_family"] == "Solutions Architect"


def test_invariant_security_not_required_without_strong_trigger() -> None:
    # Generic mentions of security/privacy should not mark Security as required.
    out = extract_ai_fields(
        {
            "title": "Value Realization Lead, AI Deployment and Adoption",
            "jd_text": "We partner with Security and follow privacy best practices. Drive adoption and onboarding.",
        }
    )
    assert "Security" not in out["skills_required"]
    assert "Security" in out["skills_preferred"]
    assert out.get("security_required_reason") == ""
    assert out.get("security_required_match") == ""
    assert out.get("security_required_context") == ""

    # Strong compliance/clearance triggers should force Security into required.
    out2 = extract_ai_fields(
        {
            "title": "Solutions Architect, Gov",
            "jd_text": "Security clearance required. Travel up to 30%.",
        }
    )
    assert "Security" in out2["skills_required"]
    assert "Security" not in out2["skills_preferred"]
    assert out2.get("security_required_reason") == "security clearance"
    assert "security clearance" in str(out2.get("security_required_match") or "").lower()
    assert len(str(out2.get("security_required_match") or "")) <= 80
    assert len(str(out2.get("security_required_context") or "")) <= 220


def test_invariant_security_required_reason_ts_sci() -> None:
    out = extract_ai_fields(
        {
            "title": "Forward Deployed Engineer, Gov",
            "jd_text": "Active TS/SCI clearance. Work with customers.",
        }
    )
    assert "Security" in out["skills_required"]
    assert out.get("security_required_reason") == "security clearance"
    assert "ts/sci" in str(out.get("security_required_match") or "").lower()
    assert len(str(out.get("security_required_match") or "")) <= 80
    assert len(str(out.get("security_required_context") or "")) <= 220


def test_invariant_security_required_reason_fedramp() -> None:
    out = extract_ai_fields(
        {
            "title": "Solutions Architect, Gov",
            "jd_text": "FedRAMP required. Deploy systems.",
        }
    )
    assert "Security" in out["skills_required"]
    assert out.get("security_required_reason") == "compliance requirement"
    assert "fedramp" in str(out.get("security_required_match") or "").lower()
    assert len(str(out.get("security_required_match") or "")) <= 80


def test_invariant_cs_role_has_nonzero_match_score_with_current_profile() -> None:
    """
    Ensure at least one CS/adoption role yields a non-zero match_score given the checked-in
    candidate_profile.json (protects against accidental token/label drift).
    """
    repo_root = Path(__file__).resolve().parents[1]
    profile = json.loads((repo_root / "data" / "candidate_profile.json").read_text(encoding="utf-8"))

    job = {
        "title": "Value Realization Lead, AI Deployment and Adoption",
        "team": "Go To Market, Customer Success",
        "location": "Remote (US)",
        "jd_text": """
        Drive adoption and onboarding; build enablement and change management playbooks.
        Partner with executive stakeholders; define ROI / KPIs for value realization.
        Follow privacy best practices.
        """,
    }
    ai = extract_ai_fields(job)
    score, _notes = compute_match(ai, profile)
    assert score > 0


def test_invariant_security_required_if_trigger_before_boilerplate_cutoff() -> None:
    job = {
        "title": "Solutions Architect, Gov",
        "jd_text": """
        Requirements:
        - Security clearance required.
        - Python and APIs.

        About OpenAI
        This footer should be ignored.
        """,
    }
    out = extract_ai_fields(job)
    assert "Security" in out["skills_required"]


def test_invariant_security_not_required_if_trigger_only_after_boilerplate_cutoff() -> None:
    job = {
        "title": "Solutions Architect, Gov",
        "jd_text": """
        Requirements:
        - Python and APIs.
        - Follow security and privacy best practices.

        About OpenAI
        Security clearance required.
        """,
    }
    out = extract_ai_fields(job)
    # Trigger occurs only after cutoff => must not force Security required.
    assert "Security" not in out["skills_required"]
    # Generic security mention before cutoff may still place it in preferred.
    assert "Security" in out["skills_preferred"]
