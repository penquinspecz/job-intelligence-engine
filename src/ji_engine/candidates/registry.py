from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ji_engine.config import (
    DEFAULT_CANDIDATE_ID,
    STATE_DIR,
    candidate_history_dir,
    candidate_profile_path,
    candidate_run_metadata_dir,
    candidate_state_dir,
    candidate_state_paths,
    candidate_user_state_dir,
    sanitize_candidate_id,
)
from ji_engine.utils.atomic_write import atomic_write_text
from ji_engine.utils.time import utc_now_z

CANDIDATE_PROFILE_SCHEMA_VERSION = 1
CANDIDATE_REGISTRY_SCHEMA_VERSION = 1
CANDIDATE_PROFILE_FILENAME = "candidate_profile.json"
CANDIDATE_REGISTRY_FILENAME = "registry.json"
PROFILE_TEXT_MAX_BYTES = {
    "resume_text": 120_000,
    "linkedin_text": 120_000,
    "summary_text": 40_000,
}


class CandidateTextInputs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resume_text: Optional[str] = None
    linkedin_text: Optional[str] = None
    summary_text: Optional[str] = None


class CandidateTextArtifactPointer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    kind: Literal["resume_text", "linkedin_text", "summary_text"]
    sha256: str
    size_bytes: int = Field(ge=1)
    captured_at_utc: str
    artifact_path: str


class CandidateTextInputArtifacts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resume_text: Optional[CandidateTextArtifactPointer] = None
    linkedin_text: Optional[CandidateTextArtifactPointer] = None
    summary_text: Optional[CandidateTextArtifactPointer] = None


class CandidateConstraints(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allow_remote: bool = True
    max_commute_minutes: int = Field(default=90, ge=0, le=600)


class CandidateProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = CANDIDATE_PROFILE_SCHEMA_VERSION
    candidate_id: str
    display_name: str
    target_roles: List[str] = Field(default_factory=list)
    preferred_locations: List[str] = Field(default_factory=list)
    constraints: CandidateConstraints = Field(default_factory=CandidateConstraints)
    text_inputs: CandidateTextInputs = Field(default_factory=CandidateTextInputs)
    text_input_artifacts: CandidateTextInputArtifacts = Field(default_factory=CandidateTextInputArtifacts)


class CandidateRegistryEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    profile_path: str


class CandidateRegistry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = CANDIDATE_REGISTRY_SCHEMA_VERSION
    candidates: List[CandidateRegistryEntry] = Field(default_factory=list)


class CandidateValidationError(ValueError):
    pass


def candidate_registry_path() -> Path:
    return STATE_DIR / "candidates" / CANDIDATE_REGISTRY_FILENAME


def _registry_path() -> Path:
    return candidate_registry_path()


def _profile_path(candidate_id: str) -> Path:
    return candidate_profile_path(candidate_id)


def _legacy_profile_path(candidate_id: str) -> Path:
    return candidate_state_dir(candidate_id) / CANDIDATE_PROFILE_FILENAME


def _profile_inputs_dir(candidate_id: str) -> Path:
    return candidate_state_dir(candidate_id) / "inputs"


def _profile_artifacts_dir(candidate_id: str) -> Path:
    return _profile_inputs_dir(candidate_id) / "artifacts"


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
    _validate_profile_text_inputs(profile.text_inputs)
    return profile


def _validate_profile_text_inputs(text_inputs: CandidateTextInputs) -> None:
    for kind, max_bytes in PROFILE_TEXT_MAX_BYTES.items():
        value = getattr(text_inputs, kind)
        if value is None:
            continue
        size = len(value.encode("utf-8"))
        if size > max_bytes:
            raise CandidateValidationError(f"{kind} exceeds max bytes ({size} > {max_bytes})")


def _text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _ingest_one_text(candidate_id: str, kind: str, text: str) -> CandidateTextArtifactPointer:
    max_bytes = PROFILE_TEXT_MAX_BYTES[kind]
    size = len(text.encode("utf-8"))
    if size > max_bytes:
        raise CandidateValidationError(f"{kind} exceeds max bytes ({size} > {max_bytes})")

    sha256 = _text_sha256(text)
    captured_at = utc_now_z(seconds_precision=True)
    stamp = captured_at.replace("-", "").replace(":", "")
    artifact_name = f"{stamp}_{kind}_{sha256[:16]}.json"
    artifact_path = _profile_artifacts_dir(candidate_id) / artifact_name
    artifact_payload = {
        "schema_version": 1,
        "candidate_id": candidate_id,
        "kind": kind,
        "sha256": sha256,
        "size_bytes": size,
        "captured_at_utc": captured_at,
        "text": text,
    }
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    if not artifact_path.exists():
        atomic_write_text(artifact_path, _dump_json(artifact_payload))
    return CandidateTextArtifactPointer(
        schema_version=1,
        kind=kind,  # type: ignore[arg-type]
        sha256=sha256,
        size_bytes=size,
        captured_at_utc=captured_at,
        artifact_path=str(artifact_path.relative_to(STATE_DIR)),
    )


def load_candidate_profile(candidate_id: str) -> CandidateProfile:
    safe_id = sanitize_candidate_id(candidate_id)
    path = _profile_path(safe_id)
    if not path.exists():
        legacy_path = _legacy_profile_path(safe_id)
        if legacy_path.exists():
            path = legacy_path
        else:
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
    paths = candidate_state_paths(safe_id)
    paths.user_inputs.mkdir(parents=True, exist_ok=True)
    paths.system_state.mkdir(parents=True, exist_ok=True)
    _profile_artifacts_dir(safe_id).mkdir(parents=True, exist_ok=True)

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
        "registry_path": str(candidate_registry_path()),
    }


def set_profile_text(
    candidate_id: str,
    *,
    resume_text: Optional[str] = None,
    linkedin_text: Optional[str] = None,
    summary_text: Optional[str] = None,
) -> Dict[str, Any]:
    safe_id = sanitize_candidate_id(candidate_id)
    updates = {
        "resume_text": resume_text,
        "linkedin_text": linkedin_text,
        "summary_text": summary_text,
    }
    provided = [k for k, v in updates.items() if v is not None]
    if not provided:
        raise CandidateValidationError("at least one text field is required")

    profile = load_candidate_profile(safe_id)
    text_inputs = profile.text_inputs.model_copy(deep=True)
    text_artifacts = profile.text_input_artifacts.model_copy(deep=True)

    emitted: Dict[str, Any] = {}
    for kind in provided:
        text = updates[kind] or ""
        setattr(text_inputs, kind, text)
        pointer = _ingest_one_text(safe_id, kind, text)
        setattr(text_artifacts, kind, pointer)
        emitted[kind] = pointer.model_dump()

    updated = profile.model_copy(update={"text_inputs": text_inputs, "text_input_artifacts": text_artifacts})
    profile_path = write_candidate_profile(updated)
    return {
        "candidate_id": safe_id,
        "profile_path": str(profile_path),
        "updated_fields": sorted(provided),
        "text_input_artifacts": emitted,
    }


def candidate_text_input_provenance(candidate_id: str) -> Dict[str, Any]:
    safe_id = sanitize_candidate_id(candidate_id)
    profile = load_candidate_profile(safe_id)
    pointers = profile.text_input_artifacts
    artifacts: Dict[str, Dict[str, Any]] = {}
    for kind in ("resume_text", "linkedin_text", "summary_text"):
        pointer = getattr(pointers, kind)
        if pointer is not None:
            artifacts[kind] = pointer.model_dump()
    return {
        "candidate_id": safe_id,
        "text_input_artifacts": artifacts,
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
