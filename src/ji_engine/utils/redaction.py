"""
SignalCraft
Copyright (c) 2026 Chris Menendez.
All Rights Reserved.
See LICENSE for permitted use.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Finding:
    pattern: str
    snippet: str
    location: str


_AWS_ACCESS_KEY_RE = re.compile(r"\b(AKIA|ASIA)[0-9A-Z]{16}\b")
_AWS_SECRET_KV_RE = re.compile(r"(?i)aws_secret_access_key\s*[:=]\s*([A-Za-z0-9/+=]{40})")
_DISCORD_WEBHOOK_RE = re.compile(r"https://(?:canary\.|ptb\.)?discord(?:app)?\.com/api/webhooks/\d+/[A-Za-z0-9._-]+")
_BEARER_RE = re.compile(r"\b[Bb]earer\s+[A-Za-z0-9._-]{20,}\b")
_GITHUB_TOKEN_RE = re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}\b")
_GITHUB_PAT_RE = re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b")
_OPENAI_KEY_RE = re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")

_TEXT_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("aws_access_key_id", _AWS_ACCESS_KEY_RE),
    ("discord_webhook", _DISCORD_WEBHOOK_RE),
    ("bearer_token", _BEARER_RE),
    ("github_token", _GITHUB_TOKEN_RE),
    ("github_pat", _GITHUB_PAT_RE),
    ("openai_api_key", _OPENAI_KEY_RE),
)


def _clip(text: str, limit: int = 120) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def scan_text_for_secrets(text: str) -> list[Finding]:
    findings: list[Finding] = []
    for name, pattern in _TEXT_RULES:
        for match in pattern.finditer(text):
            findings.append(
                Finding(
                    pattern=name,
                    snippet=_clip(match.group(0)),
                    location=f"offset:{match.start()}",
                )
            )

    # Tighten AWS secret detection to avoid random-string false positives:
    # only flag secret key when an access key id is also present in the same text.
    if _AWS_ACCESS_KEY_RE.search(text):
        for match in _AWS_SECRET_KV_RE.finditer(text):
            findings.append(
                Finding(
                    pattern="aws_secret_access_key_pair",
                    snippet=_clip(match.group(0)),
                    location=f"offset:{match.start()}",
                )
            )
    return findings


def scan_json_for_secrets(obj: Any) -> list[Finding]:
    findings: list[Finding] = []

    def walk(value: Any, path: str) -> None:
        if isinstance(value, dict):
            for key in sorted(value.keys(), key=lambda k: str(k)):
                child = value[key]
                next_path = f"{path}.{key}" if path else str(key)
                walk(child, next_path)
            return
        if isinstance(value, list):
            for idx, child in enumerate(value):
                next_path = f"{path}[{idx}]"
                walk(child, next_path)
            return
        if isinstance(value, str):
            for finding in scan_text_for_secrets(value):
                findings.append(
                    Finding(
                        pattern=finding.pattern,
                        snippet=finding.snippet,
                        location=path or "$",
                    )
                )

    walk(obj, "")
    return findings
