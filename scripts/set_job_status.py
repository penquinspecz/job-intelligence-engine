#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from ji_engine.config import USER_STATE_DIR
from ji_engine.utils.atomic_write import atomic_write_text
from ji_engine.utils.job_identity import job_identity
from ji_engine.utils.user_state import load_user_state


def _normalize_status(value: str) -> str:
    return value.strip().lower()


def _load_state(path: Path) -> Dict[str, Dict[str, Any]]:
    try:
        data = load_user_state(path)
    except Exception:
        return {}
    if isinstance(data, dict):
        if all(isinstance(v, dict) for v in data.values()):
            return {str(k): v for k, v in data.items()}
    return {}


def _write_state(path: Path, state: Dict[str, Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True)
    atomic_write_text(path, payload)


def _job_id_from_url(url: str) -> str:
    return job_identity({"apply_url": url})


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Update user job state.")
    parser.add_argument("--profile", default="cs", help="Profile name (default: cs).")
    parser.add_argument("--job-id", help="Stable job id to update.")
    parser.add_argument("--url", help="Apply/detail URL to derive job id.")
    parser.add_argument(
        "--status",
        required=True,
        choices=["applied", "ignore", "interviewing", "saved", "none"],
        help="Status to set (or none to remove).",
    )
    parser.add_argument("--note", help="Optional note.")
    args = parser.parse_args(argv)

    if bool(args.job_id) == bool(args.url):
        print("ERROR: provide exactly one of --job-id or --url", file=sys.stderr)
        return 2

    job_id = args.job_id or _job_id_from_url(args.url or "")
    if not job_id:
        print("ERROR: failed to derive job id", file=sys.stderr)
        return 2

    state_path = USER_STATE_DIR / f"{args.profile}.json"
    state = _load_state(state_path)

    status = _normalize_status(args.status)
    if status == "none":
        state.pop(job_id, None)
    else:
        record: Dict[str, Any] = {"status": status.upper()}
        if args.note:
            record["notes"] = args.note
        state[job_id] = record

    _write_state(state_path, state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
