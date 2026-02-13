from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ji_engine.config import (
    DEFAULT_CANDIDATE_ID,
    STATE_DIR,
    candidate_history_dir,
    candidate_run_metadata_dir,
    candidate_state_dir,
    candidate_user_state_dir,
    sanitize_candidate_id,
)
from ji_engine.utils.atomic_write import atomic_write_text

CANDIDATE_PROFILE_SCHEMA_VERSION = 1
CANDIDATE_REGISTRY_SCHEMA_VERSION = 1
CANDIDATE_PROFILE_FILENAME = "candidate_profile.json"


class CandidateConstraints(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allow_remote: bool = True
    max_commute_minutes: int = Field(default=90, ge=0, le=600)


class CandidateProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = CANDIDATE_PROFILE_SCHEMA_VERSION
    candidate_id: str
    display_name: str
    target_roles: List[str] = Field(default_factory=list)
    preferred_locations: List[str] = Field(default_factory=list)
    constraints: CandidateConstraints = Field(default_factory=CandidateConstraints)


class CandidateRegistryEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    profile_path: str


class CandidateRegistry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = CANDIDATE_REGISTRY_SCHEMA_VERSION
    candidates: List[CandidateRegistryEntry] = Field(default_factory=list)


class CandidateValidationError(ValueError):
    pass


def _registry_path() -> Path:
    return STATE_DIR / "candidates" / "registry.json"


def _profile_path(candidate_id: str) -> Path:
    return candidate_state_dir(candidate_id) / CANDIDATE_PROFILE_FILENAME


def _load_json(path: Path) -> Dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise CandidateValidationError(f"invalid JSON object in {path}")
    return payload


def _dump_json(payload: Dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)


def _normalize_registry(registry: CandidateRegistry) -> CandidateRegistry:
    entries: List[CandidateRegistryEntry] = []
    seen: set[str] = set()
    for entry in sorted(registry.candidates, key=lambda item: item.candidate_id):
        candidate_id = sanitize_candidate_id(entry.candidate_id)
        if candidate_id in seen:
            raise CandidateValidationError(f"duplicate candidate_id in registry: {candidate_id}")
        seen.add(candidate_id)
        entries.append(CandidateRegistryEntry(candidate_id=candidate_id, profile_path=entry.profile_path))
    return CandidateRegistry(schema_version=CANDIDATE_REGISTRY_SCHEMA_VERSION, candidates=entries)


def load_registry() -> CandidateRegistry:
    path = _registry_path()
    if not path.exists():
        registry = CandidateRegistry(
            schema_version=CANDIDATE_REGISTRY_SCHEMA_VERSION,
            candidates=[
                CandidateRegistryEntry(
                    candidate_id=DEFAULT_CANDIDATE_ID,
                    profile_path=str(_profile_path(DEFAULT_CANDIDATE_ID).relative_to(STATE_DIR)),
                )
            ],
        )
        save_registry(registry)
        return registry
    try:
        payload = _load_json(path)
        registry = CandidateRegistry.model_validate(payload)
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        raise CandidateValidationError(f"invalid candidate registry: {path}: {exc}") from exc
    return _normalize_registry(registry)


def save_registry(registry: CandidateRegistry) -> None:
    path = _registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = _normalize_registry(registry)
    atomic_write_text(path, _dump_json(normalized.model_dump()))


def _normalize_profile(profile: CandidateProfile, expected_candidate_id: str) -> CandidateProfile:
    safe_id = sanitize_candidate_id(expected_candidate_id)
    if sanitize_candidate_id(profile.candidate_id) != safe_id:
        raise CandidateValidationError(
            f"candidate profile candidate_id mismatch: expected {safe_id}, got {profile.candidate_id}"
        )
    if profile.schema_version != CANDIDATE_PROFILE_SCHEMA_VERSION:
        raise CandidateValidationError(f"unsupported candidate profile schema_version '{profile.schema_version}'")
    return profile


def load_candidate_profile(candidate_id: str) -> CandidateProfile:
    safe_id = sanitize_candidate_id(candidate_id)
    path = _profile_path(safe_id)
    if not path.exists():
        raise CandidateValidationError(f"candidate profile missing: {path}")
    try:
        payload = _load_json(path)
        profile = CandidateProfile.model_validate(payload)
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        raise CandidateValidationError(f"invalid candidate profile: {path}: {exc}") from exc
    return _normalize_profile(profile, safe_id)


def write_candidate_profile(profile: CandidateProfile) -> Path:
    safe_id = sanitize_candidate_id(profile.candidate_id)
    normalized = _normalize_profile(profile, safe_id)
    path = _profile_path(safe_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, _dump_json(normalized.model_dump()))
    return path


def _profile_skeleton(candidate_id: str, display_name: str | None = None) -> CandidateProfile:
    safe_id = sanitize_candidate_id(candidate_id)
    name = (display_name or safe_id).strip() or safe_id
    return CandidateProfile(
        schema_version=CANDIDATE_PROFILE_SCHEMA_VERSION,
        candidate_id=safe_id,
        display_name=name,
        target_roles=[],
        preferred_locations=[],
        constraints=CandidateConstraints(),
    )


def add_candidate(candidate_id: str, display_name: str | None = None) -> Dict[str, str]:
    safe_id = sanitize_candidate_id(candidate_id)

    registry = load_registry()
    existing_ids = {entry.candidate_id for entry in registry.candidates}
    if safe_id in existing_ids:
        raise CandidateValidationError(f"candidate already exists: {safe_id}")

    candidate_state_dir(safe_id).mkdir(parents=True, exist_ok=True)
    candidate_run_metadata_dir(safe_id).mkdir(parents=True, exist_ok=True)
    candidate_history_dir(safe_id).mkdir(parents=True, exist_ok=True)
    candidate_user_state_dir(safe_id).mkdir(parents=True, exist_ok=True)

    profile = _profile_skeleton(safe_id, display_name)
    profile_path = write_candidate_profile(profile)

    registry.candidates.append(
        CandidateRegistryEntry(
            candidate_id=safe_id,
            profile_path=str(profile_path.relative_to(STATE_DIR)),
        )
    )
    save_registry(registry)

    return {
        "candidate_id": safe_id,
        "profile_path": str(profile_path),
        "candidate_dir": str(candidate_state_dir(safe_id)),
    }


def list_candidates() -> List[Dict[str, str]]:
    registry = load_registry()
    out: List[Dict[str, str]] = []
    for entry in sorted(registry.candidates, key=lambda item: item.candidate_id):
        out.append(
            {
                "candidate_id": entry.candidate_id,
                "profile_path": entry.profile_path,
            }
        )
    return out


def validate_candidate_profiles() -> Tuple[bool, List[str]]:
    errors: List[str] = []
    try:
        registry = load_registry()
    except CandidateValidationError as exc:
        return False, [str(exc)]

    for entry in registry.candidates:
        candidate_id = sanitize_candidate_id(entry.candidate_id)
        expected_rel = str(_profile_path(candidate_id).relative_to(STATE_DIR))
        if entry.profile_path != expected_rel:
            errors.append(
                f"registry profile_path mismatch for {candidate_id}: expected {expected_rel}, got {entry.profile_path}"
            )
            continue
        try:
            load_candidate_profile(candidate_id)
        except CandidateValidationError as exc:
            errors.append(str(exc))

    return len(errors) == 0, sorted(errors)
