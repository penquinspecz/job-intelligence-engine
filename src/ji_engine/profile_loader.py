"""SignalCraft
Copyright (c) 2026 Chris Menendez.
All Rights Reserved.
See LICENSE for permitted use.

Load and validate candidate profile from JSON file."""

import json
from pathlib import Path
from typing import List

from pydantic import BaseModel, Field


class Basics(BaseModel):
    """Basic candidate information."""

    name: str
    current_role: str
    years_experience: int
    current_company: str


class Preferences(BaseModel):
    """Job search preferences."""

    target_companies: List[str]
    target_locations: List[str]
    target_roles: List[str]
    anti_patterns: List[str]
    seniority_level: str


class Skills(BaseModel):
    """Candidate skills organized by category."""

    technical_core: List[str]
    ai_specific: List[str]
    customer_success: List[str]
    domain_knowledge: List[str]


class Constraints(BaseModel):
    """Job search constraints and preferences."""

    willing_to_travel_percent: int = Field(ge=0, le=100)
    team_size_min: int = Field(ge=0)
    team_size_max: int = Field(ge=0)
    prefers_hands_on_technical: bool


class CandidateProfile(BaseModel):
    """Complete candidate profile matching candidate_profile.json structure."""

    basics: Basics
    preferences: Preferences
    skills: Skills
    constraints: Constraints
    narrative_bio: str


def load_candidate_profile(path: str = "data/candidate_profile.json") -> CandidateProfile:
    """
    Load and validate candidate profile from JSON file.

    Args:
        path: Path to the candidate profile JSON file. Defaults to "data/candidate_profile.json".

    Returns:
        CandidateProfile: Validated candidate profile model.

    Raises:
        FileNotFoundError: If the profile file does not exist.
        json.JSONDecodeError: If the file contains invalid JSON.
        ValueError: If the JSON structure does not match the expected schema.
    """
    profile_path = Path(path)

    if not profile_path.exists():
        raise FileNotFoundError(
            f"Candidate profile file not found: {path}. Please ensure the file exists and the path is correct."
        )

    try:
        with open(profile_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise json.JSONDecodeError(
            f"Invalid JSON in candidate profile file: {path}. {str(e)}",
            e.doc,
            e.pos,
        ) from e

    try:
        return CandidateProfile(**data)
    except Exception as e:
        raise ValueError(
            f"Candidate profile validation failed for {path}. "
            f"Please check that all required fields are present and correctly formatted. "
            f"Error: {str(e)}"
        ) from e
