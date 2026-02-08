from __future__ import annotations

from pathlib import Path

from ji_engine.embeddings.simple import build_profile_text
from ji_engine.models import JobSource, RawJobPosting
from ji_engine.profile_loader import Basics, CandidateProfile, Constraints, Preferences, Skills
from ji_engine.utils.time import utc_now_naive
from scripts.run_classify import _reclassify_maybe, _select_provider


def _profile() -> CandidateProfile:
    return CandidateProfile(
        basics=Basics(name="Test", current_role="CS", years_experience=10, current_company="X"),
        preferences=Preferences(
            target_companies=[],
            target_locations=[],
            target_roles=["customer success"],
            anti_patterns=[],
            seniority_level="senior",
        ),
        skills=Skills(
            technical_core=["apis", "python"],
            ai_specific=["llm"],
            customer_success=["value realization"],
            domain_knowledge=["fintech"],
        ),
        constraints=Constraints(
            willing_to_travel_percent=10,
            team_size_min=2,
            team_size_max=10,
            prefers_hands_on_technical=True,
        ),
        narrative_bio="",
    )


def test_maybe_job_promoted_by_embedding(tmp_path: Path) -> None:
    jobs = [
        RawJobPosting(
            source=JobSource.OPENAI,
            title="Account Manager",
            location="Remote",
            team="CS",
            apply_url="u1",
            detail_url="d1",
            raw_text="We need customer success and value realization with APIs experience.",
            scraped_at=utc_now_naive(),
        ),
        RawJobPosting(
            source=JobSource.OPENAI,
            title="Irrelevant",
            location="Remote",
            team=None,
            apply_url="u2",
            detail_url="d2",
            raw_text="Nothing relevant.",
            scraped_at=utc_now_naive(),
        ),
    ]

    labeled = [
        {"relevance": "MAYBE"},
        {"relevance": "IRRELEVANT"},
    ]

    provider = _select_provider("stub", None)
    profile_vec = provider.embed(build_profile_text(_profile()))
    cache_path = tmp_path / "embed_cache.json"

    _reclassify_maybe(jobs, labeled, profile_vec, provider, cache_path, threshold=0.2)

    assert labeled[0]["relevance"] == "RELEVANT"
    assert labeled[1]["relevance"] == "IRRELEVANT"
    assert cache_path.exists()
