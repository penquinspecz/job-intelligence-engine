"""
SignalCraft
Copyright (c) 2026 Chris Menendez.
All Rights Reserved.
See LICENSE for permitted use.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

BACKOFF_RE = re.compile(r"\[provider_retry\]\[backoff\]")
CIRCUIT_RE = re.compile(r"\[provider_retry\]\[circuit_breaker\]")
ROBOTS_RE = re.compile(r"\[provider_retry\]\[robots\]")
PROVENANCE_RE = re.compile(r"\[run_scrape\]\[provenance\]\s+(\{.*\})")


@dataclass(frozen=True)
class ScriptedStatusSequence:
    statuses: tuple[int, ...]

    @classmethod
    def parse(cls, raw: str) -> "ScriptedStatusSequence":
        values: list[int] = []
        for token in raw.split(","):
            token = token.strip()
            if not token:
                continue
            status = int(token)
            if status < 100 or status > 599:
                raise ValueError(f"invalid HTTP status: {status}")
            values.append(status)
        if not values:
            raise ValueError("status sequence cannot be empty")
        return cls(statuses=tuple(values))

    def status_for_request(self, request_index: int) -> int:
        if request_index < 0:
            raise ValueError("request_index must be >= 0")
        if request_index >= len(self.statuses):
            return self.statuses[-1]
        return self.statuses[request_index]


def build_failure_html() -> str:
    # Keep this minimal and deterministic, while parseable by AshbyProvider fallback parsing.
    return (
        "<html><body>"
        "<a href='https://jobs.ashbyhq.com/proof/00000000-0000-0000-0000-000000000000/application'>"
        "Proof Role"
        "</a>"
        "</body></html>"
    )


def extract_provenance_payloads(log_text: str) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for raw in PROVENANCE_RE.findall(log_text):
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            payloads.append(payload)
    return payloads


def extract_provenance_payload(log_text: str) -> dict[str, Any] | None:
    payloads = extract_provenance_payloads(log_text)
    return payloads[-1] if payloads else None


def provider_payload(provenance: dict[str, Any], provider_id: str) -> dict[str, Any] | None:
    if "live_attempted" in provenance:
        return provenance
    value = provenance.get(provider_id)
    if isinstance(value, dict):
        return value
    return None


def extract_event_lines(log_text: str) -> dict[str, list[str]]:
    lines = log_text.splitlines()
    return {
        "backoff": [line for line in lines if BACKOFF_RE.search(line)],
        "circuit_breaker": [line for line in lines if CIRCUIT_RE.search(line)],
        "robots": [line for line in lines if ROBOTS_RE.search(line)],
        "provenance": [line for line in lines if "[run_scrape][provenance]" in line],
    }


def required_politeness_issues(
    *,
    log_text: str,
    provider_id: str,
) -> list[str]:
    issues: list[str] = []
    events = extract_event_lines(log_text)
    if not events["backoff"]:
        issues.append("missing [provider_retry][backoff] line")
    if not events["circuit_breaker"]:
        issues.append("missing [provider_retry][circuit_breaker] line")
    if not events["robots"]:
        issues.append("missing [provider_retry][robots] line")
    payload = None
    for provenance in extract_provenance_payloads(log_text):
        candidate = provider_payload(provenance, provider_id)
        if candidate is not None:
            payload = candidate
            break
    if payload is None:
        issues.append("missing provenance payload")
        return issues
    if payload.get("mode") != "LIVE":
        issues.append("provenance.mode must be LIVE")
    if payload.get("attempts_made") is None:
        issues.append("provenance.attempts_made is required")
    if payload.get("live_attempted") is not True:
        issues.append("provenance.live_attempted must be true")
    return issues
