from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class JobSource(str, Enum):
    OPENAI = "openai"
    ASHBY = "ashby"
    # Future: ANTHROPIC = "anthropic", etc.


@dataclass
class RawJobPosting:
    """
    Minimal, provider-agnostic representation of a job as scraped from the web.
    This is what the scraper produces before any LLM / embedding magic happens.
    """

    source: JobSource
    title: str
    location: Optional[str]
    team: Optional[str]
    apply_url: str
    detail_url: Optional[str]
    raw_text: str
    scraped_at: datetime
    job_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        # Convert datetime to ISO so it’s JSON-serializable
        d["scraped_at"] = self.scraped_at.isoformat()
        # Enum to plain string
        d["source"] = self.source.value
        return d


@dataclass
class StructuredJobProfile:
    """
    Future stage: output of the classification / embedding pipeline.
    Keeping it simple for now so Sprint 1 stays focused on scraping.
    """

    source: JobSource
    title: str
    location: Optional[str]
    team: Optional[str]

    # Simple tags for now; later can be LLM-derived categories, seniority, etc.
    categories: List[str]
    skills: List[str]
    seniority: Optional[str]

    raw_ref: RawJobPosting

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["source"] = self.source.value
        d["raw_ref"] = self.raw_ref.to_dict()
        return d


@dataclass
class CandidateProfile:
    """
    Logical representation of *you* as a candidate.
    This will eventually be read from a candidate_profile.json file.
    """

    name: str
    target_companies: List[str]
    target_functions: List[str]  # e.g. ["Customer Success", "Solutions Architect"]
    target_locations: List[str]  # human-readable strings
    skills: List[str]
    years_experience: int
    notes: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
