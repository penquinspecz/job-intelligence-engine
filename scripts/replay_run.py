#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ji_engine.config import RUN_METADATA_DIR


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fp:
        for chunk in iter(lambda: fp.read(8192), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sanitize_run_id(run_id: str) -> str:
    return run_id.replace(":", "").replace("-", "").replace(".", "")


def _load_run_report(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _validate_entry(label: str, path_str: Optional[str], expected_hash: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    if not path_str or not expected_hash:
        return f"{label}: missing path/hash", None
    path = Path(path_str)
    if not path.exists():
        return f"{label}: missing file {path}", None
    actual = _sha256(path)
    if actual != expected_hash:
        return None, f"{label}: sha256 mismatch (expected={expected_hash} actual={actual})"
    return None, None


def _collect_entries(report: Dict[str, Any], profile: str) -> List[Tuple[str, Optional[str], Optional[str]]]:
    entries: List[Tuple[str, Optional[str], Optional[str]]] = []

    inputs = report.get("inputs") or {}
    if isinstance(inputs, dict):
        for key, value in inputs.items():
            if isinstance(value, dict):
                entries.append((f"input:{key}", value.get("path"), value.get("sha256")))

    scoring_inputs = report.get("scoring_inputs_by_profile") or {}
    if isinstance(scoring_inputs, dict):
        value = scoring_inputs.get(profile)
        if isinstance(value, dict):
            entries.append((f"scoring_input:{profile}", value.get("path"), value.get("sha256")))

    outputs = report.get("outputs_by_profile") or {}
    if isinstance(outputs, dict):
        value = outputs.get(profile)
        if isinstance(value, dict):
            for key, output in value.items():
                if isinstance(output, dict):
                    entries.append((f"output:{profile}:{key}", output.get("path"), output.get("sha256")))

    return entries


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Verify run report inputs/outputs match hashes.")
    parser.add_argument("--run-report", type=str, help="Path to run report JSON.")
    parser.add_argument("--run-id", type=str, help="Run id to locate under state/runs.")
    parser.add_argument("--profile", type=str, default="cs", help="Profile to validate (default: cs).")
    args = parser.parse_args(argv)

    if not args.run_report and not args.run_id:
        print("ERROR: provide --run-report or --run-id", file=sys.stderr)
        return 2

    report_path: Optional[Path] = None
    if args.run_report:
        report_path = Path(args.run_report)
    else:
        run_id = _sanitize_run_id(args.run_id or "")
        report_path = RUN_METADATA_DIR / f"{run_id}.json"

    if not report_path.exists():
        print(f"ERROR: run report not found at {report_path}", file=sys.stderr)
        return 2

    try:
        report = _load_run_report(report_path)
    except Exception as exc:
        print(f"ERROR: failed to load run report: {exc!r}", file=sys.stderr)
        return 3

    entries = _collect_entries(report, args.profile)
    if not entries:
        print("ERROR: run report missing inputs/outputs for profile", file=sys.stderr)
        return 2

    validation_errors: List[str] = []
    mismatches: List[str] = []
    for label, path_str, expected_hash in entries:
        val_err, mismatch = _validate_entry(label, path_str, expected_hash)
        if val_err:
            validation_errors.append(val_err)
        if mismatch:
            mismatches.append(mismatch)

    if validation_errors:
        print("FAIL: missing files or invalid report entries")
        for err in validation_errors:
            print(f"- {err}")
        if mismatches:
            for err in mismatches:
                print(f"- {err}")
        return 2

    if mismatches:
        print("FAIL: hash mismatches detected")
        for err in mismatches:
            print(f"- {err}")
        return 3

    print("PASS: all referenced inputs and outputs match report hashes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
