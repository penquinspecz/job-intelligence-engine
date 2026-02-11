from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Tuple

MIN_BYTES_DEFAULT = 500
MIN_BYTES_BY_PROVIDER = {
    "openai": 500,
    "anthropic": 500,
    "ashby": 500,
}
BLOCKED_MARKERS = (
    "access denied",
    "forbidden",
    "verify you are human",
    "temporarily blocked",
    "request blocked",
    "attention required",
)
CLOUDFLARE_MARKERS = (
    "<title>just a moment</title>",
    "cdn-cgi/challenge-platform",
    "cf_chl_opt",
    "cloudflare",
)
ASHBY_MARKERS = (
    "ashbyhq.com",
    "jobs.ashbyhq.com",
    "ashby",
    "jobposting",
    "application/ld+json",
)


@dataclass(frozen=True)
class ValidationResult:
    provider: str
    path: Path
    ok: bool
    reason: str
    skipped: bool = False


def _default_data_dir() -> Path:
    return Path(os.environ.get("JOBINTEL_DATA_DIR") or "data")


def _resolve_snapshot_path(entry: dict, data_dir: Path) -> Path:
    snapshot_path = Path(entry.get("snapshot_path") or "")
    if snapshot_path.is_absolute():
        return snapshot_path
    parts = snapshot_path.parts
    if parts and parts[0] == "data":
        return data_dir / Path(*parts[1:])
    return data_dir / snapshot_path


def _min_bytes_for(provider: str) -> int:
    env_key = f"JOBINTEL_SNAPSHOT_MIN_BYTES_{provider.upper()}"
    env_value = os.environ.get(env_key)
    if env_value:
        try:
            return int(env_value)
        except ValueError:
            pass
    env_default = os.environ.get("JOBINTEL_SNAPSHOT_MIN_BYTES")
    if env_default:
        try:
            return int(env_default)
        except ValueError:
            pass
    return MIN_BYTES_BY_PROVIDER.get(provider, MIN_BYTES_DEFAULT)


def _looks_blocked(text: str) -> Tuple[bool, str]:
    lower = text.lower()
    for marker in CLOUDFLARE_MARKERS:
        if marker in lower:
            return True, "cloudflare challenge page"
    if "captcha" in lower and (
        "verify you are human" in lower
        or "access denied" in lower
        or "temporarily blocked" in lower
        or "attention required" in lower
    ):
        return True, "blocked marker: captcha"
    for marker in BLOCKED_MARKERS:
        if marker in lower:
            return True, f"blocked marker: {marker}"
    return False, "ok"


def _requires_ashby_markers(extraction_mode: str | None, provider: str) -> bool:
    if provider in {"ashby", "anthropic"}:
        return True
    return False


def _requires_jsonld_markers(extraction_mode: str | None) -> bool:
    return extraction_mode == "jsonld"


def _has_ashby_marker(text: str) -> bool:
    lower = text.lower()
    return any(marker in lower for marker in ASHBY_MARKERS)


def _preview_text(content: bytes, limit: int = 200) -> str:
    text = content.decode("utf-8", errors="ignore")
    text = " ".join(text.split())
    return text[:limit]


def validate_snapshot_bytes(
    provider: str,
    content: bytes,
    *,
    extraction_mode: str | None = None,
) -> Tuple[bool, str]:
    if not content:
        return False, "empty content"

    if extraction_mode == "snapshot_json":
        try:
            payload = json.loads(content.decode("utf-8"))
        except Exception as exc:
            return False, f"invalid json: {exc}"
        if not isinstance(payload, list):
            return False, "snapshot json must be a list"
        return True, "ok"

    min_bytes = _min_bytes_for(provider)
    if len(content) < min_bytes:
        return False, f"content too small ({len(content)} bytes)"

    text = content.decode("utf-8", errors="ignore")
    if not text.strip():
        return False, "empty content"

    if _requires_ashby_markers(extraction_mode, provider) and not _has_ashby_marker(text):
        return False, "missing ashby markers"
    if _requires_jsonld_markers(extraction_mode) and "application/ld+json" not in text.lower():
        return False, "missing jsonld markers"

    blocked, reason = _looks_blocked(text)
    if blocked:
        return False, reason

    lower = text.lower()
    if "<html" not in lower and "<!doctype html" not in lower and "</html" not in lower:
        return False, "missing html tags"

    return True, "ok"


def validate_snapshot_file(
    provider: str,
    path: Path,
    *,
    extraction_mode: str | None = None,
    **kwargs: object,
) -> Tuple[bool, str]:
    # Back-compat for older call sites that pass provider mode as `type=...`.
    if extraction_mode is None and "type" in kwargs:
        alias_mode = kwargs.pop("type")
        if isinstance(alias_mode, str):
            extraction_mode = alias_mode
    if kwargs:
        bad = ", ".join(sorted(str(key) for key in kwargs))
        raise TypeError(f"validate_snapshot_file() got unexpected keyword argument(s): {bad}")

    if not path.exists():
        return False, "missing file"

    try:
        content = path.read_bytes()
    except Exception as exc:
        return False, f"read failed: {exc}"

    ok, reason = validate_snapshot_bytes(provider, content, extraction_mode=extraction_mode)
    if not ok:
        preview = _preview_text(content)
        reason = f"{reason}; bytes={len(content)}; preview={preview}"
    return ok, reason


def validate_snapshots(
    providers_cfg: Iterable[dict],
    *,
    provider_ids: Iterable[str] | None = None,
    data_dir: Path | None = None,
    validate_all: bool = False,
) -> List[ValidationResult]:
    base_dir = data_dir or _default_data_dir()
    provider_map = {entry["provider_id"]: entry for entry in providers_cfg}
    requested = [item.strip() for item in (provider_ids or []) if str(item).strip()]
    if validate_all:
        requested = sorted(provider_map.keys())
    if not requested and not validate_all:
        requested = ["openai"]

    results: List[ValidationResult] = []
    for provider in requested:
        if provider not in provider_map:
            raise ValueError(f"Unknown provider '{provider}'.")
        entry = provider_map[provider]
        snapshot_enabled = bool(entry.get("snapshot_enabled", True))
        extraction_mode = str(entry.get("extraction_mode") or entry.get("type") or "snapshot_json")
        snapshot_path = _resolve_snapshot_path(entry, base_dir)
        if not snapshot_enabled:
            results.append(
                ValidationResult(
                    provider=provider,
                    path=snapshot_path,
                    ok=True,
                    reason="skipped: snapshot_disabled",
                    skipped=True,
                )
            )
            continue
        if validate_all and not snapshot_path.exists():
            results.append(
                ValidationResult(
                    provider=provider,
                    path=snapshot_path,
                    ok=True,
                    reason="skipped: snapshot_missing",
                    skipped=True,
                )
            )
            continue
        ok, reason = validate_snapshot_file(provider, snapshot_path, extraction_mode=extraction_mode)
        results.append(ValidationResult(provider=provider, path=snapshot_path, ok=ok, reason=reason))
    return results
