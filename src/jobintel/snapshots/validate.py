from __future__ import annotations

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


def _default_data_dir() -> Path:
    return Path(os.environ.get("JOBINTEL_DATA_DIR") or "data")


def _snapshot_path_for(provider: str, data_dir: Path) -> Path:
    if provider == "openai":
        return data_dir / "openai_snapshots" / "index.html"
    if provider == "anthropic":
        return data_dir / "anthropic_snapshots" / "index.html"
    raise ValueError(f"Unknown provider '{provider}'.")


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


def _requires_ashby_markers(provider: str) -> bool:
    return provider in {"ashby", "anthropic"}


def _has_ashby_marker(text: str) -> bool:
    lower = text.lower()
    return any(marker in lower for marker in ASHBY_MARKERS)


def _preview_text(content: bytes, limit: int = 200) -> str:
    text = content.decode("utf-8", errors="ignore")
    text = " ".join(text.split())
    return text[:limit]


def validate_snapshot_bytes(provider: str, content: bytes) -> Tuple[bool, str]:
    if not content:
        return False, "empty content"

    min_bytes = _min_bytes_for(provider)
    if len(content) < min_bytes:
        return False, f"content too small ({len(content)} bytes)"

    text = content.decode("utf-8", errors="ignore")
    if not text.strip():
        return False, "empty content"

    if _requires_ashby_markers(provider) and not _has_ashby_marker(text):
        return False, "missing ashby markers"

    blocked, reason = _looks_blocked(text)
    if blocked:
        return False, reason

    lower = text.lower()
    if "<html" not in lower and "<!doctype html" not in lower and "</html" not in lower:
        return False, "missing html tags"

    return True, "ok"


def validate_snapshot_file(provider: str, path: Path) -> Tuple[bool, str]:
    if not path.exists():
        return False, "missing file"

    try:
        content = path.read_bytes()
    except Exception as exc:
        return False, f"read failed: {exc}"

    ok, reason = validate_snapshot_bytes(provider, content)
    if not ok:
        preview = _preview_text(content)
        reason = f"{reason}; bytes={len(content)}; preview={preview}"
    return ok, reason


def validate_snapshots(
    providers: Iterable[str],
    *,
    data_dir: Path | None = None,
) -> List[ValidationResult]:
    base_dir = data_dir or _default_data_dir()
    results: List[ValidationResult] = []
    for provider in providers:
        snapshot_path = _snapshot_path_for(provider, base_dir)
        ok, reason = validate_snapshot_file(provider, snapshot_path)
        results.append(ValidationResult(provider=provider, path=snapshot_path, ok=ok, reason=reason))
    return results
