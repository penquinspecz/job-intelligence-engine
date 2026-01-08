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

    # Strong compliance/clearance triggers should force Security into required.
    out2 = extract_ai_fields(
        {
            "title": "Solutions Architect, Gov",
            "jd_text": "Security clearance required. Travel up to 30%.",
        }
    )
    assert "Security" in out2["skills_required"]
    assert "Security" not in out2["skills_preferred"]


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

