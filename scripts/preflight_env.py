#!/usr/bin/env python3
from __future__ import annotations

try:
    import _bootstrap  # type: ignore
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

import argparse
import os
import sys
from typing import Iterable, List, Set, Tuple


def _truthy(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _region_present() -> bool:
    return bool(os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or os.getenv("JOBINTEL_AWS_REGION"))


def _required_for_mode(mode: str) -> Tuple[List[str], List[str]]:
    required: List[str] = []
    notes: List[str] = []
    if mode in {"publish", "verify"}:
        required.append("JOBINTEL_S3_BUCKET")
        if not _region_present():
            required.append("AWS_REGION|AWS_DEFAULT_REGION|JOBINTEL_AWS_REGION")
            notes.append("missing region")
    return required, notes


def _optional_vars() -> List[str]:
    return [
        "JOBINTEL_S3_PREFIX",
        "PUBLISH_S3",
        "PUBLISH_S3_DRY_RUN",
        "CAREERS_MODE",
        "EMBED_PROVIDER",
        "ENRICH_MAX_WORKERS",
        "JOBINTEL_DASHBOARD_URL",
        "DISCORD_WEBHOOK_URL",
        "AI_ENABLED",
        "OPENAI_API_KEY",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AWS_PROFILE",
    ]


def _present_vars(candidates: Iterable[str]) -> Set[str]:
    present: Set[str] = set()
    for name in candidates:
        if name == "AWS_REGION|AWS_DEFAULT_REGION|JOBINTEL_AWS_REGION":
            if _region_present():
                present.add(name)
            continue
        if os.getenv(name):
            present.add(name)
    return present


def _format_list(values: Iterable[str]) -> str:
    items = sorted(values)
    return ", ".join(items) if items else "<none>"


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="JobIntel env preflight (offline, deterministic).")
    parser.add_argument(
        "--mode",
        choices=["run", "publish", "verify"],
        default="run",
        help="Validation mode (run: no publish; publish: publish-enabled; verify: operator verify).",
    )
    args = parser.parse_args(argv)

    try:
        required, _notes = _required_for_mode(args.mode)
        optional = _optional_vars()

        ai_enabled = _truthy(os.getenv("AI_ENABLED"))
        if ai_enabled and not os.getenv("OPENAI_API_KEY"):
            required.append("OPENAI_API_KEY")

        present = _present_vars(required + optional)
        missing_required = [name for name in required if name not in present]
        missing_optional = [name for name in optional if name not in present]

        print(f"MODE: {args.mode}")
        print(f"REQUIRED: {_format_list(required)}")
        print(f"OPTIONAL: {_format_list(optional)}")
        print(f"PRESENT: {_format_list(present)}")

        if missing_required:
            print(f"MISSING REQUIRED: {_format_list(missing_required)}", file=sys.stderr)
        if missing_optional:
            print(f"MISSING OPTIONAL: {_format_list(missing_optional)}", file=sys.stderr)

        return 0 if not missing_required else 2
    except Exception as exc:
        print(f"ERROR: runtime error during preflight: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
