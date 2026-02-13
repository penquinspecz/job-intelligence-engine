"""
SignalCraft
Copyright (c) 2026 Chris Menendez.
All Rights Reserved.
See LICENSE for permitted use.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

USER_STATE_SCHEMA_VERSION = 1
USER_STATE_STATUSES = ("ignore", "saved", "applied", "interviewing")


def normalize_user_status(value: Any) -> str:
    text = " ".join(str(value).split()).strip().lower()
    return text


def _is_legacy_map(payload: Any) -> bool:
    return isinstance(payload, dict) and all(isinstance(v, dict) for v in payload.values())


def _is_schema_map(payload: Any) -> bool:
    return (
        isinstance(payload, dict)
        and int(payload.get("schema_version") or 0) == USER_STATE_SCHEMA_VERSION
        and isinstance(payload.get("jobs"), dict)
    )


def _normalize_record(raw: Dict[str, Any]) -> Dict[str, Any]:
    status = normalize_user_status(raw.get("status", ""))
    if status not in USER_STATE_STATUSES:
        raise ValueError(f"unsupported status: {status!r}")
    out: Dict[str, Any] = {"status": status}
    date = raw.get("date")
    notes = raw.get("notes")
    if isinstance(date, str) and date.strip():
        out["date"] = date.strip()
    if isinstance(notes, str) and notes.strip():
        out["notes"] = notes.strip()
    return out


def load_user_state_checked(path: Path) -> Tuple[Dict[str, Dict[str, Any]], Optional[str]]:
    """
    Load user state with validation.
    Returns:
      - normalized mapping keyed by job_id
      - optional warning string (for invalid/unreadable files)
    """
    if not path.exists():
        return {}, None

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {}, f"invalid user_state JSON at {path}: {exc}"

    source: Dict[str, Any]
    if _is_schema_map(payload):
        source = payload["jobs"]
    elif _is_legacy_map(payload):
        source = payload
    else:
        return {}, (
            f"invalid user_state schema at {path}: expected "
            f'{{"schema_version": {USER_STATE_SCHEMA_VERSION}, "jobs": {{...}}}}'
        )

    normalized: Dict[str, Dict[str, Any]] = {}
    for key in sorted(source):
        raw = source.get(key)
        if not isinstance(raw, dict):
            return {}, f"invalid user_state entry at {path}: {key!r} must map to an object"
        try:
            normalized[str(key)] = _normalize_record(raw)
        except ValueError as exc:
            return {}, f"invalid user_state entry at {path}: {key!r} ({exc})"
    return normalized, None


def load_user_state(path: Path) -> Dict[str, Dict[str, Any]]:
    data, warning = load_user_state_checked(path)
    if warning:
        raise ValueError(warning)
    return data


def build_user_state_document(jobs: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    normalized: Dict[str, Dict[str, Any]] = {}
    for job_id in sorted(jobs):
        normalized[str(job_id)] = _normalize_record(jobs[job_id])
    return {"schema_version": USER_STATE_SCHEMA_VERSION, "jobs": normalized}
