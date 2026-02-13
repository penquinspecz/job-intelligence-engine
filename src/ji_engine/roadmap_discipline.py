"""
SignalCraft
Copyright (c) 2026 Chris Menendez.
All Rights Reserved.
See LICENSE for permitted use.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

LAST_VERIFIED_RE = re.compile(r"^Last verified:\s*`([^`]+)`\s*@\s*`([0-9a-f]{7,40})`\s*$", re.MULTILINE)
SHA_RE = re.compile(r"^[0-9a-f]{7,40}$")

ROADMAP_PATH = "docs/ROADMAP.md"

RECEIPT_PREFIXES = ("ops/proof/bundles/",)
CORE_PIPELINE_PREFIXES = (
    "scripts/run_daily.py",
    "scripts/run_scrape.py",
    "scripts/publish_s3.py",
    "src/ji_engine/",
)


@dataclass(frozen=True)
class RoadmapStamp:
    timestamp_utc: str
    sha: str


@dataclass(frozen=True)
class GuardFinding:
    code: str
    message: str
    level: str  # warn | error


@dataclass(frozen=True)
class GuardResult:
    findings: tuple[GuardFinding, ...]

    @property
    def has_errors(self) -> bool:
        return any(f.level == "error" for f in self.findings)

    @property
    def has_warnings(self) -> bool:
        return any(f.level == "warn" for f in self.findings)


def parse_last_verified_stamp(roadmap_text: str) -> RoadmapStamp | None:
    match = LAST_VERIFIED_RE.search(roadmap_text)
    if not match:
        return None
    timestamp_utc, sha = match.group(1), match.group(2)
    return RoadmapStamp(timestamp_utc=timestamp_utc, sha=sha)


def _is_receipt_path(path: str) -> bool:
    return path.startswith(RECEIPT_PREFIXES)


def _is_core_pipeline_path(path: str) -> bool:
    return path.startswith(CORE_PIPELINE_PREFIXES)


def evaluate_roadmap_guard(
    *,
    stamp: RoadmapStamp | None,
    changed_files: list[str],
    head_sha: str | None,
    files_since_stamp: list[str] | None = None,
    commits_since_stamp: int | None = None,
    stale_commit_threshold: int = 50,
) -> GuardResult:
    findings: list[GuardFinding] = []
    if stamp is None:
        findings.append(
            GuardFinding(
                code="missing_last_verified_stamp",
                level="error",
                message="docs/ROADMAP.md is missing a parseable 'Last verified' stamp.",
            )
        )
        return GuardResult(findings=tuple(findings))
    if not SHA_RE.match(stamp.sha):
        findings.append(
            GuardFinding(
                code="invalid_stamp_sha",
                level="error",
                message=f"Last verified SHA is not valid hex: {stamp.sha!r}",
            )
        )

    roadmap_changed = ROADMAP_PATH in changed_files
    changed_receipts = sorted(path for path in changed_files if _is_receipt_path(path))
    changed_core = sorted(path for path in changed_files if _is_core_pipeline_path(path))

    if changed_receipts and not roadmap_changed:
        findings.append(
            GuardFinding(
                code="roadmap_required_for_receipt_changes",
                level="error",
                message=(
                    "Changes under ops/proof/bundles/ require a docs/ROADMAP.md update in the same PR. "
                    f"Found {len(changed_receipts)} receipt path changes."
                ),
            )
        )

    if changed_core and not roadmap_changed:
        findings.append(
            GuardFinding(
                code="roadmap_missing_for_core_changes",
                level="warn",
                message=(
                    "Core pipeline files changed without docs/ROADMAP.md changes. "
                    f"Found {len(changed_core)} core file changes."
                ),
            )
        )

    if head_sha and SHA_RE.match(head_sha) and stamp.sha != head_sha:
        sensitive_since_stamp = []
        if files_since_stamp:
            sensitive_since_stamp = sorted(
                path for path in files_since_stamp if _is_receipt_path(path) or _is_core_pipeline_path(path)
            )
        if sensitive_since_stamp and not roadmap_changed:
            findings.append(
                GuardFinding(
                    code="stamp_stale_vs_sensitive_changes",
                    level="warn",
                    message=(
                        "Last verified SHA is behind HEAD and sensitive paths changed since stamp "
                        "without roadmap updates."
                    ),
                )
            )
        if commits_since_stamp is not None and commits_since_stamp > stale_commit_threshold and sensitive_since_stamp:
            findings.append(
                GuardFinding(
                    code="stamp_wildly_stale",
                    level="warn",
                    message=(
                        f"Last verified SHA is {commits_since_stamp} commits behind HEAD with sensitive changes "
                        f"(threshold={stale_commit_threshold})."
                    ),
                )
            )

    return GuardResult(findings=tuple(findings))
