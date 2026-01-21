from __future__ import annotations

import re
from typing import Any, Dict, Optional

STATE_ABBREVS = (
    "AL",
    "AK",
    "AZ",
    "AR",
    "CA",
    "CO",
    "CT",
    "DE",
    "FL",
    "GA",
    "HI",
    "ID",
    "IL",
    "IN",
    "IA",
    "KS",
    "KY",
    "LA",
    "ME",
    "MD",
    "MA",
    "MI",
    "MN",
    "MS",
    "MO",
    "MT",
    "NE",
    "NV",
    "NH",
    "NJ",
    "NM",
    "NY",
    "NC",
    "ND",
    "OH",
    "OK",
    "OR",
    "PA",
    "RI",
    "SC",
    "SD",
    "TN",
    "TX",
    "UT",
    "VT",
    "VA",
    "WA",
    "WV",
    "WI",
    "WY",
    "DC",
)

_STATE_PATTERN = "(?:" + "|".join(STATE_ABBREVS) + ")"
_US_KEYWORDS = r"(?:united states|u\.s\.a\.|u\.s\.|usa)"
_REMOTE_US_PATTERNS = [
    re.compile(rf"\bremote\b.*{_US_KEYWORDS}", re.IGNORECASE),
    re.compile(rf"{_US_KEYWORDS}.*\bremote\b", re.IGNORECASE),
]
_EXPLICIT_US = re.compile(_US_KEYWORDS, re.IGNORECASE)
_CITY_STATE = re.compile(rf"\b([A-Za-z .'-]+),\s*({_STATE_PATTERN})\b")
_STATE_ONLY = re.compile(rf"(?:,|\s)\s*({_STATE_PATTERN})\b")


def _normalize_text(value: Optional[str]) -> str:
    if not value:
        return ""
    return " ".join(value.strip().split())


def normalize_location_guess(title: Optional[str], location: Optional[str]) -> Dict[str, Any]:
    location_norm = _normalize_text(location)
    combined_raw = _normalize_text(f"{title or ''} {location or ''}")
    combined = combined_raw.lower()

    if not combined and not location_norm:
        return {
            "location_norm": location_norm,
            "is_us_or_remote_us_guess": False,
            "us_guess_reason": "none",
        }

    if "remote" in combined and re.search(r"\bUS\b", combined_raw):
        return {
            "location_norm": location_norm,
            "is_us_or_remote_us_guess": True,
            "us_guess_reason": "remote_us",
        }

    for pattern in _REMOTE_US_PATTERNS:
        if pattern.search(combined):
            return {
                "location_norm": location_norm,
                "is_us_or_remote_us_guess": True,
                "us_guess_reason": "remote_us",
            }

    if re.search(r"\bUS\b", combined_raw):
        return {
            "location_norm": location_norm,
            "is_us_or_remote_us_guess": True,
            "us_guess_reason": "explicit_us",
        }

    if _EXPLICIT_US.search(combined):
        return {
            "location_norm": location_norm,
            "is_us_or_remote_us_guess": True,
            "us_guess_reason": "explicit_us",
        }

    if location_norm:
        city_state_match = _CITY_STATE.search(location_norm)
        if city_state_match:
            return {
                "location_norm": location_norm,
                "is_us_or_remote_us_guess": True,
                "us_guess_reason": "city_state",
            }

        state_match = _STATE_ONLY.search(location_norm)
        if state_match:
            return {
                "location_norm": location_norm,
                "is_us_or_remote_us_guess": True,
                "us_guess_reason": "state_abbrev",
            }

    return {
        "location_norm": location_norm,
        "is_us_or_remote_us_guess": False,
        "us_guess_reason": "none",
    }
