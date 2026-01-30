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
                "summary": f"Stub summary for {job.get('title', '(untitled)')}",
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
        # Deterministic, realistic placeholders; keep structure stable for tests/fixtures.
        return {
            "resume_bullets": [
                (f"Drove adoption of an AI/ML solution aligned to {title}, quantifying business impact."),
                "Partnered with product/eng to ship iterative improvements based on user feedback.",
                "Built customer-facing demos that reduced time-to-value and increased retention.",
                "Documented runbooks and playbooks to scale delivery and onboarding.",
            ],
            "cover_letter_points": [
                f"Map prior wins to the goals of the {title} team.",
                "Show customer empathy and ability to translate needs into shipped changes.",
                "Highlight cross-functional delivery (PM, Eng, GTM) and post-launch iteration.",
            ],
            "interview_prompts": [
                "Describe a time you unblocked a deployment under tight constraints.",
                "Share how you handled ambiguous requirements and aligned stakeholders.",
                "Walk through a demo you built that moved a key KPI.",
                "Explain how you measured value realization after launch.",
                "Discuss a postmortem you led and the follow-up actions you drove.",
            ],
            "star_prompts": [
                (
                    "Situation/Task: customer blocked on integration; "
                    "Action: triage, ship fix; "
                    "Result: uptime/retention gains."
                ),
                ("Situation/Task: unclear scope; Action: align stakeholders, define MVP; Result: on-time launch."),
                ("Situation/Task: low adoption; Action: build demo + enablement; Result: increased usage."),
                ("Situation/Task: perf issue; Action: profile, optimize; Result: latency/error-rate reduction."),
                ("Situation/Task: security concern; Action: coordinate fix/review; Result: risk mitigated."),
            ],
            "gap_plan": [
                "Day 1: Read team charters and recent postmortems; note top risks.",
                "Day 2: Review product/docs; list required skills and map current strengths/gaps.",
                "Day 3: Build a tiny demo targeting a core workflow; measure baseline.",
                "Day 4: Pair with a peer to validate approach; incorporate feedback.",
                "Day 5: Draft enablement snippet (runbook or FAQ) for the demo.",
                "Day 6: Deep dive one missing skill (course/notes); apply to demo.",
                "Day 7: Polish demo UX + logging; rehearse narrative.",
                "Day 8: Add simple metrics to show value (latency, accuracy, adoption proxy).",
                "Day 9: Write a short retro on demo findings and next steps.",
                "Day 10: Expand demo to second scenario; capture comparison data.",
                "Day 11: Validate with a mock customer conversation; log objections.",
                "Day 12: Address objections with small changes; update runbook.",
                "Day 13: Final pass on docs/screenshots; prep sharing plan.",
                "Day 14: Publish internal shareout; capture feedback and follow-ups.",
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
                "summary": f"Live summary for {job.get('title', '(untitled)')}",
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
