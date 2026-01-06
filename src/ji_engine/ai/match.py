from __future__ import annotations

from typing import Any, Dict, Iterable, List, Set, Tuple

from ji_engine.ai.schema import ensure_ai_payload


def _to_lower_set(items: Iterable[Any]) -> Set[str]:
    return {str(i).strip().lower() for i in items if str(i).strip()}


def _candidate_skills(profile: Dict[str, Any]) -> Set[str]:
    skills = profile.get("skills", {}) or {}
    all_lists = []
    for lst in skills.values():
        if lst:
            all_lists.extend(lst)
    return _to_lower_set(all_lists)


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
    required = _to_lower_set(ai.get("skills_required", []))
    preferred = _to_lower_set(ai.get("skills_preferred", []))

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

