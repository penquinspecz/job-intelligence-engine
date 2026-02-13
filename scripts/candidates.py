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


def _load_text_value(raw_text: str | None, file_path: str | None) -> str | None:
    if raw_text is not None and file_path is not None:
        raise ValueError("pass either text or file, not both")
    if raw_text is not None:
        return raw_text
    if file_path is None:
        return None
    return Path(file_path).read_text(encoding="utf-8")


def cmd_ingest_text(args: argparse.Namespace) -> int:
    candidate_registry = args.registry_module
    try:
        resume_text = _load_text_value(args.resume_text, args.resume_file)
        linkedin_text = _load_text_value(args.linkedin_text, args.linkedin_file)
        summary_text = _load_text_value(args.summary_text, args.summary_file)
        result = candidate_registry.set_profile_text(
            args.candidate_id,
            resume_text=resume_text,
            linkedin_text=linkedin_text,
            summary_text=summary_text,
        )
    except (OSError, candidate_registry.CandidateValidationError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(result, sort_keys=True))
    else:
        fields = ",".join(result.get("updated_fields") or [])
        print(f"updated candidate text candidate_id={result['candidate_id']} fields={fields}")
    return 0


def _print_bootstrap_next_steps(candidate_id: str) -> None:
    print("next_steps:")
    print(f"  python scripts/candidates.py ingest-text {candidate_id} --resume-file ./resume.txt --json")
    print(f"  python scripts/candidates.py ingest-text {candidate_id} --linkedin-file ./linkedin.txt --json")
    print(f"  python -m jobintel.cli run daily --candidate-id {candidate_id} --profiles cs --offline --no_post")


def cmd_bootstrap(args: argparse.Namespace) -> int:
    candidate_registry = args.registry_module
    try:
        result = candidate_registry.bootstrap_candidate(args.candidate_id, args.display_name)
    except (candidate_registry.CandidateValidationError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(result, sort_keys=True))
    else:
        print(
            "bootstrapped candidate "
            f"candidate_id={result['candidate_id']} profile_path={result['profile_path']} candidate_dir={result['candidate_dir']}"
        )
        _print_bootstrap_next_steps(result["candidate_id"])
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    candidate_registry = args.registry_module
    try:
        result = candidate_registry.doctor_candidate(args.candidate_id)
    except (candidate_registry.CandidateValidationError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(result, sort_keys=True))
    else:
        status = "OK" if result["ok"] else "INVALID"
        print(f"candidate doctor: {status} candidate_id={result['candidate_id']}")
        for name, exists in sorted(result["directories"].items()):
            label = "OK" if exists else "MISSING"
            print(f"  [{label}] dir:{name}")
        profile = result["profile"]
        if profile["schema_valid"]:
            print(f"  [OK] profile:{profile['path']}")
        else:
            print(f"  [FAIL] profile:{profile['path']}")
        for kind, pointer in sorted(result["text_input_artifacts"].items()):
            if pointer["exists"] and pointer["in_candidate_root"]:
                print(f"  [OK] pointer:{kind} path={pointer['artifact_path']}")
            else:
                print(f"  [FAIL] pointer:{kind} path={pointer['artifact_path']}")
        if result["errors"]:
            print("errors:", file=sys.stderr)
            for err in result["errors"]:
                print(f"- {err}", file=sys.stderr)
    return 0 if result["ok"] else 2


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

    bootstrap_cmd = sub.add_parser("bootstrap", help="Create canonical candidate scaffold + template profile")
    bootstrap_cmd.add_argument("candidate_id")
    bootstrap_cmd.add_argument("--display-name")
    bootstrap_cmd.add_argument("--json", action="store_true")
    bootstrap_cmd.set_defaults(func=cmd_bootstrap)

    validate_cmd = sub.add_parser("validate", help="Validate candidate profiles")
    validate_cmd.add_argument("--json", action="store_true")
    validate_cmd.set_defaults(func=cmd_validate)

    doctor_cmd = sub.add_parser("doctor", help="Validate one candidate scaffold/profile/artifact pointers")
    doctor_cmd.add_argument("candidate_id")
    doctor_cmd.add_argument("--json", action="store_true")
    doctor_cmd.set_defaults(func=cmd_doctor)

    ingest_cmd = sub.add_parser("ingest-text", help="Set pasted profile text fields (no URL fetching)")
    ingest_cmd.add_argument("candidate_id")
    ingest_cmd.add_argument("--resume-text")
    ingest_cmd.add_argument("--resume-file")
    ingest_cmd.add_argument("--linkedin-text")
    ingest_cmd.add_argument("--linkedin-file")
    ingest_cmd.add_argument("--summary-text")
    ingest_cmd.add_argument("--summary-file")
    ingest_cmd.add_argument("--json", action="store_true")
    ingest_cmd.set_defaults(func=cmd_ingest_text)

    set_profile_text_cmd = sub.add_parser("set-profile-text", help="Alias for ingest-text")
    set_profile_text_cmd.add_argument("candidate_id")
    set_profile_text_cmd.add_argument("--resume-text")
    set_profile_text_cmd.add_argument("--resume-file")
    set_profile_text_cmd.add_argument("--linkedin-text")
    set_profile_text_cmd.add_argument("--linkedin-file")
    set_profile_text_cmd.add_argument("--summary-text")
    set_profile_text_cmd.add_argument("--summary-file")
    set_profile_text_cmd.add_argument("--json", action="store_true")
    set_profile_text_cmd.set_defaults(func=cmd_ingest_text)

    args = parser.parse_args(argv)
    args.registry_module = _load_registry_module(args.state_dir)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
