from __future__ import annotations

from typing import Any, Dict, List

AI_REQUIRED_KEYS = {
    "summary": str,
    "confidence": float,
    "notes": str,
    "skills_required": list,
    "skills_preferred": list,
    "role_family": str,
    "seniority": str,
    "match_score": int,
    "summary_bullets": list,
    "red_flags": list,
}


def _as_list_of_str(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value]
    return [str(value)]


def ensure_ai_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize AI payload to include all required keys with defaults.
    - Lists are coerced to list[str]
    - match_score is clamped to [0, 100]
    """
    match_score_raw = payload.get("match_score", 0)
    try:
        match_score_int = int(match_score_raw)
    except Exception:
        match_score_int = 0
    match_score_int = max(0, min(100, match_score_int))

    return {
        "summary": str(payload.get("summary", "")),
        "confidence": float(payload.get("confidence", 0.0)),
        "notes": str(payload.get("notes", "")),
        "skills_required": _as_list_of_str(payload.get("skills_required")),
        "skills_preferred": _as_list_of_str(payload.get("skills_preferred")),
        "role_family": str(payload.get("role_family", "")),
        "seniority": str(payload.get("seniority", "")),
        "match_score": match_score_int,
        "summary_bullets": _as_list_of_str(payload.get("summary_bullets")),
        "red_flags": _as_list_of_str(payload.get("red_flags")),
        "rules_version": str(payload.get("rules_version", "")),
    }

