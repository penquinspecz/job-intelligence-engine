from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from ji_engine.utils.redaction import scan_text_for_secrets


@dataclass(frozen=True)
class SecretMatch:
    pattern: str
    match: str


_SECRET_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("aws_access_key_id", re.compile(r"\b(AKIA|ASIA)[0-9A-Z]{16}\b")),
    (
        "discord_webhook",
        re.compile(r"https://(?:canary\.|ptb\.)?discord(?:app)?\.com/api/webhooks/\d+/[A-Za-z0-9._-]+"),
    ),
    ("bearer_token", re.compile(r"\b[Bb]earer\s+[A-Za-z0-9._-]{20,}\b")),
    ("github_token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}\b")),
    ("github_pat", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b")),
    ("openai_api_key", re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")),
    (
        "aws_secret_access_key",
        re.compile(r"(?i)aws_secret_access_key\s*[:=]\s*[A-Za-z0-9/+=]{20,}"),
    ),
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def find_secret_matches(text: str) -> list[SecretMatch]:
    matches: list[SecretMatch] = []
    for finding in scan_text_for_secrets(text):
        matches.append(SecretMatch(pattern=finding.pattern, match=finding.snippet))
    return matches


def redact_text(text: str) -> str:
    out = text
    for name, pattern in _SECRET_RULES:
        out = pattern.sub(f"[{name.upper()}_REDACTED]", out)
    return out


def assert_no_secrets(path: Path, text: str, *, allow_secrets: bool = False) -> None:
    if allow_secrets:
        return
    findings = find_secret_matches(text)
    if not findings:
        return
    reasons = ", ".join(sorted({f.pattern for f in findings}))
    raise ValueError(
        f"secret-like content detected in {path}. patterns={reasons}. "
        "Pass --allow-secrets to bypass for local debugging."
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_bundle_manifest(
    bundle_dir: Path,
    *,
    run_id: str,
    cluster_name: str,
    kube_context: str,
    bucket: str,
    prefix: str,
    git_sha: str,
    files: Iterable[Path],
) -> Path:
    items = []
    for path in sorted(files, key=lambda p: p.as_posix()):
        rel = path.relative_to(bundle_dir).as_posix()
        items.append(
            {
                "path": rel,
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )

    payload = {
        "schema_version": 1,
        "created_at": utc_now_iso(),
        "run_id": run_id,
        "cluster_name": cluster_name,
        "kube_context": kube_context,
        "bucket": bucket,
        "prefix": prefix,
        "git_sha": git_sha,
        "files": items,
    }
    manifest_path = bundle_dir / "bundle_manifest.json"
    manifest_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest_path


def write_bundle_readme(
    bundle_dir: Path,
    *,
    run_id: str,
    cluster_name: str,
    kube_context: str,
    bucket: str,
    prefix: str,
    git_sha: str,
) -> Path:
    readme = bundle_dir / "README.md"
    readme.write_text(
        "\n".join(
            [
                "# Milestone 3 Proof Bundle",
                "",
                f"- run_id: `{run_id}`",
                f"- captured_at: `{utc_now_iso()}`",
                f"- cluster_name: `{cluster_name}`",
                f"- kube_context: `{kube_context}`",
                f"- bucket: `{bucket}`",
                f"- prefix: `{prefix}`",
                f"- git_sha: `{git_sha}`",
                "",
                "Commit-safe guidance:",
                "- Prefer committing the redacted excerpt log when present.",
                "- Review `bundle_manifest.json` hashes before publishing receipts.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return readme


def build_excerpt_log(full_log_text: str) -> str:
    keepers = []
    patterns = (
        re.compile(r"JOBINTEL_RUN_ID="),
        re.compile(r"\[run_scrape\]\[provenance\]"),
        re.compile(r"POLICY_SUMMARY"),
        re.compile(r"PUBLISH_CONTRACT"),
        re.compile(r"s3_status=ok"),
    )
    for line in full_log_text.splitlines():
        if any(p.search(line) for p in patterns):
            keepers.append(line)
    excerpt = "\n".join(keepers) + ("\n" if keepers else "")
    return redact_text(excerpt)
