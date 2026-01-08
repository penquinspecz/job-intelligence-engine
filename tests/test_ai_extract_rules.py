from __future__ import annotations

from ji_engine.ai.extract_rules import extract_ai_fields


def test_extract_ai_fields_skills_and_flags() -> None:
    job = {
        "title": "Solutions Architect, Gov (Senior)",
        "location": "Washington, DC",
        "team": "Customer Engineering",
        "jd_text": """
        Requirements:
        - Strong Python and Kubernetes experience.
        - Infrastructure as code (Terraform) and observability.
        Preferred:
        - RAG / retrieval-augmented generation experience.
        Note: Security clearance required. Travel up to 30%.
        """,
    }
    out = extract_ai_fields(job)
    assert "Python" in out["skills_required"]
    assert "Kubernetes" in out["skills_required"]
    assert "Terraform" in out["skills_required"]
    assert out["role_family"] == "Solutions Architect"
    assert out["seniority"] in ("Senior", "Manager", "Staff", "IC")
    assert "Security clearance required" in out["red_flags"]
    assert "Travel up to 30%" in out["red_flags"]


def test_field_engineer_rules_dont_match_forward_deployed():
    job = {
        "title": "Field Engineer",
        "team": "Robotics",
        "location": "Spokane, WA",
        "jd_text": """
        Requirements:
        - Robotics and embedded systems experience.
        - Familiarity with automation, troubleshooting, and CAD.
        Preferred:
        - Experience with controls/PLC and Python scripting. Note: Travel up to 20%.
        """,
    }
    out = extract_ai_fields(job)
    assert "Robotics" in out["skills_required"]
    assert "Embedded Systems" in out["skills_required"]
    assert "Troubleshooting" in out["skills_required"]
    assert "Controls" in out["skills_required"] or "Automation" in out["skills_required"]
    assert out["role_family"] == "Robotics"
    assert out["seniority"] == "IC"
    assert "Travel up to 20%" in out["red_flags"]


def test_seniority_matches_staff_only_when_explicit():
    assert extract_ai_fields({"title": "Staff Engineer"})["seniority"] == "Staff"
    assert extract_ai_fields({"title": "Senior Support Engineer"})["seniority"] == "Senior"
    assert extract_ai_fields({"title": "Field Engineer"})["seniority"] == "IC"


def test_value_realization_does_not_emit_hw_skills_without_triggers() -> None:
    job = {
        "title": "Value Realization Lead, AI Deployment and Adoption",
        "team": "Customer Success Operations",
        "location": "Remote (US)",
        "jd_text": """
        You will drive adoption, onboarding, and value realization for enterprise customers.
        Partner with operations staff to improve processes and reporting.
        Requirements: stakeholder management, program management, analytics, security/privacy best practices.
        """,
    }
    out = extract_ai_fields(job)
    assert out["role_family"] == "Customer Success"
    assert out["role_family"] != "Field"
    # Should capture obvious CS/business skills (not just "Security").
    assert "Adoption" in out["skills_required"]
    assert "Onboarding" in out["skills_required"]
    assert "Program Management" in out["skills_required"]
    assert "Stakeholder Management" in out["skills_required"]
    assert "Enablement" in out["skills_required"] or "Change Management" in out["skills_required"]
    assert len(out["skills_required"]) >= 3
    # Should not hallucinate hardware/robotics skills without strong triggers.
    for s in ("Electromechanical", "Controls", "Embedded Systems", "CAD", "Automation", "Robotics"):
        assert s not in out["skills_required"]


def test_manager_ai_deployment_extracts_cs_skills() -> None:
    job = {
        "title": "Manager, AI Deployment - AMER",
        "team": "Go To Market, Customer Success",
        "location": "New York City",
        "jd_text": """
        About the Role
        Manage and scale a team of AI Deployment Managers.
        Drive activation and adoption through structured onboarding, training, and change management playbooks.
        Own successful deployment including integrating connectors and custom GPTs.
        Engage and influence executive stakeholders; build strong customer relationships.
        """,
    }
    out = extract_ai_fields(job)
    assert out["role_family"] == "Customer Success"
    assert out["seniority"] == "Manager"
    assert "Adoption" in out["skills_required"]
    assert "Onboarding" in out["skills_required"]
    assert "Enablement" in out["skills_required"]
    assert "Change Management" in out["skills_required"]
    assert "Implementation" in out["skills_required"]
    assert "Stakeholder Management" in out["skills_required"]

