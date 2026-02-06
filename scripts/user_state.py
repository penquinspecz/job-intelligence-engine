#!/usr/bin/env python3
from __future__ import annotations

try:
    import _bootstrap  # type: ignore
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from ji_engine.config import USER_STATE_DIR
from ji_engine.utils.atomic_write import atomic_write_text
from ji_engine.utils.job_identity import job_identity
from ji_engine.utils.user_state import (
    USER_STATE_STATUSES,
    build_user_state_document,
    load_user_state_checked,
    normalize_user_status,
)


def _profile_path(profile: str) -> Path:
    return USER_STATE_DIR / f"{profile}.json"


def _load(path: Path) -> Dict[str, Dict[str, Any]]:
    data, warning = load_user_state_checked(path)
    if warning:
        print(f"WARNING: {warning}", file=sys.stderr)
        return {}
    return data


def _write(path: Path, jobs: Dict[str, Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(build_user_state_document(jobs), ensure_ascii=False, indent=2, sort_keys=True)
    atomic_write_text(path, payload)


def _job_id_from_args(job_id: Optional[str], url: Optional[str]) -> str:
    if bool(job_id) == bool(url):
        raise ValueError("provide exactly one of --job-id or --url")
    if job_id:
        return job_id.strip()
    derived = job_identity({"apply_url": url or ""})
    if not derived:
        raise ValueError("failed to derive job id from --url")
    return derived


def cmd_add_status(args: argparse.Namespace) -> int:
    path = _profile_path(args.profile)
    jobs = _load(path)
    try:
        key = _job_id_from_args(args.job_id, args.url)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    status = normalize_user_status(args.status)
    if status not in USER_STATE_STATUSES:
        print(f"ERROR: unsupported status {status!r}", file=sys.stderr)
        return 2
    record: Dict[str, Any] = {"status": status}
    if args.date:
        record["date"] = args.date
    if args.notes:
        record["notes"] = args.notes
    jobs[key] = record
    _write(path, jobs)
    print(f"updated profile={args.profile} job_id={key} status={status}")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    path = _profile_path(args.profile)
    jobs = _load(path)
    if args.json:
        print(json.dumps(build_user_state_document(jobs), ensure_ascii=False, sort_keys=True))
        return 0
    print("job_id\tstatus\tdate\tnotes")
    for key in sorted(jobs):
        record = jobs[key]
        print(
            "\t".join(
                [
                    key,
                    str(record.get("status", "")),
                    str(record.get("date", "")),
                    str(record.get("notes", "")),
                ]
            )
        )
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    path = _profile_path(args.profile)
    jobs = _load(path)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(build_user_state_document(jobs), ensure_ascii=False, indent=2, sort_keys=True))
    print(str(out_path))
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Manage state/user_state/<profile>.json")
    sub = parser.add_subparsers(dest="cmd", required=True)

    add_status = sub.add_parser("add-status", help="Add or update status for a job_id")
    add_status.add_argument("--profile", default="cs")
    add_status.add_argument("--job-id")
    add_status.add_argument("--url")
    add_status.add_argument("--status", required=True, choices=list(USER_STATE_STATUSES))
    add_status.add_argument("--date")
    add_status.add_argument("--notes")
    add_status.set_defaults(func=cmd_add_status)

    list_cmd = sub.add_parser("list", help="List statuses for a profile")
    list_cmd.add_argument("--profile", default="cs")
    list_cmd.add_argument("--json", action="store_true")
    list_cmd.set_defaults(func=cmd_list)

    export_cmd = sub.add_parser("export", help="Export normalized user-state JSON")
    export_cmd.add_argument("--profile", default="cs")
    export_cmd.add_argument("--out", required=True)
    export_cmd.set_defaults(func=cmd_export)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
