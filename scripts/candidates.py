#!/usr/bin/env python3
from __future__ import annotations

try:
    import _bootstrap  # type: ignore
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

import argparse
import importlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Optional


def _load_registry_module(state_dir: str | None) -> Any:
    if state_dir:
        os.environ["JOBINTEL_STATE_DIR"] = str(Path(state_dir).expanduser())
    import ji_engine.candidates.registry as candidate_registry
    import ji_engine.config as config

    importlib.reload(config)
    return importlib.reload(candidate_registry)


def cmd_list(args: argparse.Namespace) -> int:
    candidates = args.registry_module.list_candidates()
    if args.json:
        print(json.dumps({"candidates": candidates}, sort_keys=True))
        return 0

    print("candidate_id\tprofile_path")
    for item in candidates:
        print(f"{item['candidate_id']}\t{item['profile_path']}")
    return 0


def cmd_add(args: argparse.Namespace) -> int:
    candidate_registry = args.registry_module
    try:
        created = candidate_registry.add_candidate(args.candidate_id, args.display_name)
    except (candidate_registry.CandidateValidationError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(created, sort_keys=True))
    else:
        print(
            "created candidate "
            f"candidate_id={created['candidate_id']} profile_path={created['profile_path']} candidate_dir={created['candidate_dir']}"
        )
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    ok, errors = args.registry_module.validate_candidate_profiles()
    if args.json:
        print(json.dumps({"ok": ok, "errors": errors}, sort_keys=True))
    else:
        if ok:
            print("candidate profiles: OK")
        else:
            print("candidate profiles: INVALID", file=sys.stderr)
            for err in errors:
                print(f"- {err}", file=sys.stderr)
    return 0 if ok else 2


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Manage file-backed candidate registry and profiles.")
    parser.add_argument(
        "--state-dir",
        help="Override state directory (sets JOBINTEL_STATE_DIR for this process).",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    list_cmd = sub.add_parser("list", help="List registered candidates")
    list_cmd.add_argument("--json", action="store_true")
    list_cmd.set_defaults(func=cmd_list)

    add_cmd = sub.add_parser("add", help="Add a candidate scaffold")
    add_cmd.add_argument("candidate_id")
    add_cmd.add_argument("--display-name")
    add_cmd.add_argument("--json", action="store_true")
    add_cmd.set_defaults(func=cmd_add)

    validate_cmd = sub.add_parser("validate", help="Validate candidate profiles")
    validate_cmd.add_argument("--json", action="store_true")
    validate_cmd.set_defaults(func=cmd_validate)

    args = parser.parse_args(argv)
    args.registry_module = _load_registry_module(args.state_dir)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
