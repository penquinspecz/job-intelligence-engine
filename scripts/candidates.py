#!/usr/bin/env python3
from __future__ import annotations

try:
    import _bootstrap  # type: ignore
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

import argparse
import json
import sys
from typing import Optional

from ji_engine.candidates.registry import (
    CandidateValidationError,
    add_candidate,
    list_candidates,
    validate_candidate_profiles,
)


def cmd_list(args: argparse.Namespace) -> int:
    candidates = list_candidates()
    if args.json:
        print(json.dumps({"candidates": candidates}, sort_keys=True))
        return 0

    print("candidate_id\tprofile_path")
    for item in candidates:
        print(f"{item['candidate_id']}\t{item['profile_path']}")
    return 0


def cmd_add(args: argparse.Namespace) -> int:
    try:
        created = add_candidate(args.candidate_id, args.display_name)
    except (CandidateValidationError, ValueError) as exc:
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
    ok, errors = validate_candidate_profiles()
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
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
