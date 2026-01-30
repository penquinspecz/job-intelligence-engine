from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Set, Tuple

from ji_engine.ai.schema import ensure_ai_payload


def _to_lower_set(items: Iterable[Any]) -> Set[str]:
    return {str(i).strip().lower() for i in items if str(i).strip()}


# Deterministic alias normalization so longer profile phrases can match canonical extractor tokens.
# Canonical tokens are lowercase.
_SKILL_ALIASES: List[Tuple[str, List[str]]] = [
    ("onboarding", [r"\bonboarding\b", r"\bcustomer onboarding\b"]),
    ("enablement", [r"\benablement\b", r"\bfield enablement\b", r"\btraining\b"]),
    ("adoption", [r"\badoption\b", r"\bactivation\b"]),
    ("change management", [r"\bchange management\b"]),
    (
        "stakeholder management",
        [r"\bstakeholder management\b", r"\bstakeholders?\b", r"\bexecutive\b", r"\bc-?level\b"],
    ),
    ("implementation", [r"\bimplementation\b", r"\bdeploy(?:ment|ing)?\b", r"\bintegration\b"]),
    ("program management", [r"\bprogram management\b"]),
    ("value measurement", [r"\bvalue measurement\b", r"\broi\b", r"\btco\b", r"\bkpis?\b", r"\bdashboards?\b"]),
    ("renewals", [r"\brenewals?\b", r"\brenewal\b", r"\bretention\b"]),
]

_SKILL_ALIAS_REGEX: List[Tuple[str, List[re.Pattern[str]]]] = [
    (canon, [re.compile(p, flags=re.IGNORECASE) for p in pats]) for canon, pats in _SKILL_ALIASES
]


def _canonicalize_skill_tokens(items: Iterable[Any]) -> Set[str]:
    """
    Convert free-form skill strings into a canonical token set (lowercase).
    If a string matches an alias pattern, we emit the canonical token(s); otherwise we emit the raw lowercased value.
    Deterministic: aliases are applied in list order, and output is a set for scoring.
    """
    out: Set[str] = set()
    for raw in items:
        s = str(raw).strip()
        if not s:
            continue
        lowered = s.lower()
        matched = False
        for canon, regs in _SKILL_ALIAS_REGEX:
            if any(r.search(lowered) for r in regs):
                out.add(canon)
                matched = True
        if not matched:
            out.add(lowered)
    return out


def _candidate_skills(profile: Dict[str, Any]) -> Set[str]:
    skills = profile.get("skills", {}) or {}
    all_lists = []
    for lst in skills.values():
        if lst:
            all_lists.extend(lst)
    return _canonicalize_skill_tokens(all_lists)


def _candidate_roles(profile: Dict[str, Any]) -> Set[str]:
    prefs = profile.get("preferences", {}) or {}
    return _to_lower_set(prefs.get("target_roles", []) or [])


def _candidate_seniority(profile: Dict[str, Any]) -> str:
    prefs = profile.get("preferences", {}) or {}
    return str(prefs.get("seniority_level", "") or "").strip().lower()


def compute_match(ai_payload: Dict[str, Any], candidate_profile: Dict[str, Any]) -> Tuple[int, List[str]]:
    """
    Compute a deterministic match score (0-100) between AI payload and candidate profile.

    Scoring (simple, deterministic):
    - Required skills coverage: up to 70 points
    - Preferred skills coverage: up to 20 points
    - Role family match bonus: 5 points
    - Seniority match bonus: 5 points
    """
    ai = ensure_ai_payload(ai_payload)
    profile = candidate_profile
    if hasattr(profile, "model_dump"):
        profile = profile.model_dump()
    elif hasattr(profile, "dict"):
        profile = profile.dict()

    candidate_skill_set = _candidate_skills(profile)
    required = _canonicalize_skill_tokens(ai.get("skills_required", []))
    preferred = _canonicalize_skill_tokens(ai.get("skills_preferred", []))

    req_matches = required & candidate_skill_set
    pref_matches = preferred & candidate_skill_set

    req_ratio = len(req_matches) / len(required) if required else 0.0
    pref_ratio = len(pref_matches) / len(preferred) if preferred else 0.0

    base_score = int(round(req_ratio * 70 + pref_ratio * 20))

    # Bonuses
    role_bonus = 5 if ai.get("role_family", "").strip().lower() in _candidate_roles(profile) else 0
    sen_bonus = 5 if ai.get("seniority", "").strip().lower() == _candidate_seniority(profile) else 0

    score = max(0, min(100, base_score + role_bonus + sen_bonus))

    notes = [
        f"required_match:{len(req_matches)}/{len(required)}",
        f"preferred_match:{len(pref_matches)}/{len(preferred)}",
        f"role_bonus:{role_bonus}",
        f"seniority_bonus:{sen_bonus}",
    ]
    return score, notes


# TODO: extend with richer weighting once real AI payload fields stabilize.
