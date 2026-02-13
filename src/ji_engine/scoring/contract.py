from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from ji_engine.utils.verification import compute_sha256_file


class ScoringConfigError(ValueError):
    pass


class ScoringBlendConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    weight: float = Field(ge=0.0, le=1.0)
    min_heuristic_floor: Optional[int] = Field(default=None, ge=0)
    max_ai_contribution: Optional[int] = Field(default=None, ge=0)


class ScoringConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(default=1)
    version: str = Field(default="v1")
    algorithm_id: str
    module_path: str = Field(default="scripts/score_jobs.py")
    role_band_multipliers: Dict[str, float]
    profile_weights: Dict[str, int]
    ai_blend: ScoringBlendConfig

    @field_validator("schema_version")
    @classmethod
    def _validate_schema_version(cls, value: int) -> int:
        if value != 1:
            raise ValueError("unsupported scoring schema_version")
        return value

    @field_validator("version")
    @classmethod
    def _validate_version(cls, value: str) -> str:
        if value != "v1":
            raise ValueError("unsupported scoring model version")
        return value

    @field_validator("role_band_multipliers")
    @classmethod
    def _validate_role_band_keys(cls, value: Dict[str, float]) -> Dict[str, float]:
        expected = {"CS_CORE", "CS_ADJACENT", "SOLUTIONS", "OTHER"}
        keys = set(value.keys())
        if keys != expected:
            raise ValueError(f"role_band_multipliers keys must be exactly {sorted(expected)}")
        return value

    @field_validator("profile_weights")
    @classmethod
    def _validate_profile_weight_keys(cls, value: Dict[str, int]) -> Dict[str, int]:
        expected = {
            "boost_cs_core",
            "boost_cs_adjacent",
            "boost_solutions",
            "penalty_research_heavy",
            "penalty_low_level",
            "penalty_strong_swe_only",
            "pin_manager_ai_deployment",
        }
        keys = set(value.keys())
        if keys != expected:
            raise ValueError(f"profile_weights keys must be exactly {sorted(expected)}")
        return value


@dataclass(frozen=True)
class _Pointer:
    pointer_type: str
    path: str
    sha256: Optional[str]
    provider: Optional[str] = None
    profile: Optional[str] = None


def load_scoring_config(path: Path) -> ScoringConfig:
    if not path.exists():
        raise ScoringConfigError(f"scoring config missing: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ScoringConfigError(f"invalid scoring config JSON: {path}: {exc}") from exc
    try:
        config = ScoringConfig.model_validate(payload)
    except ValidationError as exc:
        raise ScoringConfigError(f"invalid scoring config: {path}: {exc}") from exc
    return config


def _normalize_for_hash(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _normalize_for_hash(value[k]) for k in sorted(value.keys())}
    if isinstance(value, list):
        return [_normalize_for_hash(v) for v in value]
    if isinstance(value, float):
        return format(Decimal(str(value)).quantize(Decimal("0.000000"), rounding=ROUND_HALF_EVEN), "f")
    return value


def scoring_config_sha256(config: ScoringConfig) -> str:
    normalized = _normalize_for_hash(config.model_dump(mode="python"))
    canonical = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _code_sha256(repo_root: Path, module_path: str) -> str:
    module_file = (repo_root / module_path).resolve()
    if not module_file.exists():
        raise ScoringConfigError(f"scoring module path missing for hashing: {module_file}")
    return compute_sha256_file(module_file)


def _sorted_inputs(pointers: List[_Pointer]) -> List[Dict[str, str]]:
    ordered = sorted(
        pointers,
        key=lambda p: (
            p.pointer_type,
            p.provider or "",
            p.profile or "",
            p.path,
            p.sha256 or "",
        ),
    )
    out: List[Dict[str, str]] = []
    for ptr in ordered:
        row: Dict[str, str] = {
            "pointer_type": ptr.pointer_type,
            "path": ptr.path,
            "sha256": ptr.sha256 or "",
        }
        if ptr.provider:
            row["provider"] = ptr.provider
        if ptr.profile:
            row["profile"] = ptr.profile
        out.append(row)
    return out


def _canonical_pointer_path(path: Path | str, repo_root: Path) -> str:
    root = repo_root.resolve()
    path_obj = Path(path)
    if path_obj.is_absolute():
        resolved = path_obj.resolve(strict=False)
        try:
            return resolved.relative_to(root).as_posix()
        except ValueError:
            return resolved.as_posix()
    return path_obj.as_posix()


def build_scoring_model_metadata(
    *,
    config: ScoringConfig,
    config_path: Path,
    profiles_path: Path,
    scoring_inputs_by_provider: Dict[str, Dict[str, Dict[str, Optional[str]]]],
    repo_root: Path,
) -> Dict[str, Any]:
    pointers: List[_Pointer] = []
    pointers.append(
        _Pointer(
            pointer_type="scoring_config",
            path=_canonical_pointer_path(config_path, repo_root),
            sha256=compute_sha256_file(config_path) if config_path.exists() else None,
        )
    )
    pointers.append(
        _Pointer(
            pointer_type="profiles_config",
            path=_canonical_pointer_path(profiles_path, repo_root),
            sha256=compute_sha256_file(profiles_path) if profiles_path.exists() else None,
        )
    )

    for provider, profile_map in sorted(scoring_inputs_by_provider.items()):
        for profile, meta in sorted(profile_map.items()):
            path = meta.get("path") if isinstance(meta, dict) else None
            sha = meta.get("sha256") if isinstance(meta, dict) else None
            if not path:
                continue
            pointers.append(
                _Pointer(
                    pointer_type="selected_scoring_input",
                    provider=provider,
                    profile=profile,
                    path=_canonical_pointer_path(path, repo_root),
                    sha256=str(sha) if sha else None,
                )
            )

    module_path = config.module_path
    code_sha = _code_sha256(repo_root, module_path)

    return {
        "version": config.version,
        "algorithm_id": config.algorithm_id,
        "config_sha256": scoring_config_sha256(config),
        "module_path": module_path,
        "code_sha256": code_sha,
        "inputs": _sorted_inputs(pointers),
    }


def build_scoring_model_signature(scoring_model: Dict[str, Any]) -> str:
    """
    Deterministic drift signature for tests.

    Any algorithm/config change should alter this unless version metadata is updated intentionally.
    """
    stable = {
        "version": scoring_model.get("version"),
        "algorithm_id": scoring_model.get("algorithm_id"),
        "config_sha256": scoring_model.get("config_sha256"),
        "module_path": scoring_model.get("module_path"),
        "code_sha256": scoring_model.get("code_sha256"),
        "inputs": _normalize_for_hash(scoring_model.get("inputs") or []),
    }
    payload = json.dumps(stable, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
