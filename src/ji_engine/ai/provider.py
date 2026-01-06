from __future__ import annotations

from typing import Any, Dict

from ji_engine.ai.schema import ensure_ai_payload


class AIProvider:
    """Interface for AI extraction providers."""

    def extract(self, job: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError

    def application_kit(self, job: Dict[str, Any]) -> Dict[str, Any]:
        """Generate application kit content for a job."""
        raise NotImplementedError


class StubProvider(AIProvider):
    """Default non-network provider used when ai_live is disabled."""

    def extract(self, job: Dict[str, Any]) -> Dict[str, Any]:
        return ensure_ai_payload(
            {
                "summary": f"Stub summary for {job.get('title','(untitled)')}",
                "confidence": 0.0,
                "notes": "",
                "skills_required": [],
                "skills_preferred": [],
                "role_family": "",
                "seniority": "",
                "match_score": 0,
                "summary_bullets": [],
                "red_flags": [],
            }
        )

    def application_kit(self, job: Dict[str, Any]) -> Dict[str, Any]:
        title = job.get("title", "this role")
        return {
            "resume_bullets": [
                f"Highlight measurable impact in deploying AI/ML solutions relevant to {title}.",
                "Emphasize cross-functional stakeholder management and value realization.",
            ],
            "cover_letter_points": [
                f"Connect your experience to the team's goals for {title}.",
                "Underscore customer-facing delivery and iterative improvement.",
            ],
            "interview_prompts": [
                "Explain a time you drove adoption of a technical product.",
                "Describe how you handled an ambiguous customer request with AI constraints.",
            ],
            "gap_plan": [
                "Week 1: Review product docs and recent launch notes.",
                "Week 2: Build a small demo aligning to target customer pain point.",
            ],
        }


class OpenAIProvider(AIProvider):
    """Placeholder for live OpenAI calls (only used when ai_live flag is set)."""

    def __init__(self, api_key: str):
        self.api_key = api_key

    def extract(self, job: Dict[str, Any]) -> Dict[str, Any]:
        # TODO: implement real OpenAI call; for now return a deterministic placeholder
        return ensure_ai_payload(
            {
                "summary": f"Live summary for {job.get('title','(untitled)')}",
                "confidence": 0.5,
                "notes": "live_ai_stub",
            }
        )

    def application_kit(self, job: Dict[str, Any]) -> Dict[str, Any]:
        # TODO: implement real OpenAI call; placeholder to keep behavior predictable
        title = job.get("title", "this role")
        return {
            "resume_bullets": [f"Live stub: tailor resume bullets for {title}"],
            "cover_letter_points": ["Live stub: align narrative to role impact"],
            "interview_prompts": ["Live stub: practice value realization story"],
            "gap_plan": ["Live stub: week-by-week learning plan"],
        }


# Future: register additional providers (e.g., Anthropic) as needed.

