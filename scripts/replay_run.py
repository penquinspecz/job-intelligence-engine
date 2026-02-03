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
from typing import Any, Dict, List, Optional, Tuple

from ji_engine.config import DATA_DIR, RUN_METADATA_DIR
from ji_engine.utils.verification import compute_sha256_file, verify_verifiable_artifacts


def _sanitize_run_id(run_id: str) -> str:
    return run_id.replace(":", "").replace("-", "").replace(".", "")


def _load_run_report(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


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

    return entries


def _collect_expected_outputs(report: Dict[str, Any], profile: str) -> List[Tuple[str, Optional[str], Optional[str]]]:
    outputs = report.get("outputs_by_profile") or {}
    if not isinstance(outputs, dict):
        return []
    value = outputs.get(profile)
    if not isinstance(value, dict):
        return []
    entries: List[Tuple[str, Optional[str], Optional[str]]] = []
    for key, meta in value.items():
        if isinstance(meta, dict):
            entries.append((f"output:{key}", meta.get("path"), meta.get("sha256")))
    return entries


def _collect_verifiable_entries(
    report: Dict[str, Any], base_dir: Path
) -> List[Tuple[str, Optional[str], Optional[str]]]:
    verifiable = report.get("verifiable_artifacts") or {}
    if not isinstance(verifiable, dict):
        return []
    entries: List[Tuple[str, Optional[str], Optional[str]]] = []
    for logical_key, meta in verifiable.items():
        if not isinstance(meta, dict):
            continue
        path_str = meta.get("path")
        sha256 = meta.get("sha256")
        if not path_str:
            entries.append((f"verifiable:{logical_key}", None, sha256))
            continue
        path = Path(path_str)
        if not path.is_absolute():
            path = base_dir / path
        entries.append((f"verifiable:{logical_key}", str(path), sha256))
    return entries


def _resolve_report_path(
    run_id: Optional[str], run_report: Optional[str], run_dir: Optional[str], runs_dir: Path
) -> Path:
    if run_report:
        return Path(run_report)
    if run_dir:
        return Path(run_dir) / "run_report.json"
    if not run_id:
        raise SystemExit("ERROR: provide --run-report, --run-dir, or --run-id")
    sanitized = _sanitize_run_id(run_id)
    candidate = runs_dir / f"{sanitized}.json"
    if candidate.exists():
        return candidate
    nested = runs_dir / sanitized / "run_report.json"
    if nested.exists():
        return nested
    raise SystemExit(f"ERROR: run report not found at {candidate} or {nested}")


def _print_report(lines: List[str]) -> None:
    for line in lines:
        print(line)


def _replay_report(
    report: Dict[str, Any], profile: str, strict: bool
) -> Tuple[
    int,
    List[str],
    Dict[str, Dict[str, Optional[object]]],
    Dict[str, int],
]:
    lines: List[str] = []
    checked = 0
    matched = 0
    mismatched = 0
    missing = 0
    artifacts: Dict[str, Dict[str, Optional[object]]] = {}

    entries = _collect_entries(report, profile)
    verifiable = report.get("verifiable_artifacts")
    verifiable_entries = _collect_verifiable_entries(report, DATA_DIR)
    verifiable_mismatch_by_label: Dict[str, Dict[str, Optional[str]]] = {}
    if isinstance(verifiable, dict) and verifiable_entries:
        _, verifiable_mismatches = verify_verifiable_artifacts(DATA_DIR, verifiable)
        for mismatch in verifiable_mismatches:
            label = mismatch.get("label")
            if label:
                verifiable_mismatch_by_label[label] = mismatch
        entries.extend(verifiable_entries)
    else:
        entries.extend(_collect_expected_outputs(report, profile))
    if not entries:
        return 2, ["FAIL: no inputs/outputs to verify in run report"], artifacts, {
            "checked": 0,
            "matched": 0,
            "mismatched": 0,
            "missing": 0,
        }

    lines.append("REPLAY REPORT")
    for label, path_str, expected_hash in entries:
        logical_name = label
        if label.startswith("verifiable:"):
            logical_name = label.split("verifiable:", 1)[1]
        checked += 1
        if not path_str or not expected_hash:
            missing += 1
            lines.append(f"{label}: missing path/hash expected={expected_hash} actual=None match=False")
            artifacts[logical_name] = {
                "path": path_str,
                "expected": expected_hash,
                "actual": None,
                "bytes": None,
                "match": False,
                "missing": True,
            }
            continue
        path = Path(path_str)
        if not path.exists():
            missing += 1
            lines.append(f"{label}: missing file expected={expected_hash} actual=None match=False")
            artifacts[logical_name] = {
                "path": path_str,
                "expected": expected_hash,
                "actual": None,
                "bytes": None,
                "match": False,
                "missing": True,
            }
            continue
        actual = compute_sha256_file(path)
        ok = actual == expected_hash
        if logical_name in verifiable_mismatch_by_label:
            mismatch = verifiable_mismatch_by_label[logical_name]
            reason = mismatch.get("reason") or "mismatch"
            if reason in {"missing_path_or_hash", "missing_file"}:
                missing += 1
            else:
                mismatched += 1
            artifacts[logical_name] = {
                "path": path_str,
                "expected": mismatch.get("expected") or expected_hash,
                "actual": mismatch.get("actual") or actual,
                "bytes": path.stat().st_size,
                "match": False,
                "missing": reason in {"missing_path_or_hash", "missing_file"},
            }
            lines.append(f"{label}: expected={expected_hash} actual={actual} match=False")
        else:
            if ok:
                matched += 1
            else:
                mismatched += 1
            artifacts[logical_name] = {
                "path": path_str,
                "expected": expected_hash,
                "actual": actual,
                "bytes": path.stat().st_size,
                "match": ok,
                "missing": False,
            }
            lines.append(f"{label}: expected={expected_hash} actual={actual} match={str(ok)}")

    lines.append(f"SUMMARY: checked={checked} matched={matched} mismatched={mismatched} missing={missing}")
    if missing > 0:
        lines.insert(0, "FAIL: missing artifacts")
        return (2 if strict else 0), lines, artifacts, {
            "checked": checked,
            "matched": matched,
            "mismatched": mismatched,
            "missing": missing,
        }
    if mismatched > 0:
        lines.insert(0, "FAIL: mismatched artifacts")
        return (2 if strict else 0), lines, artifacts, {
            "checked": checked,
            "matched": matched,
            "mismatched": mismatched,
            "missing": missing,
        }
    lines.insert(0, "PASS: all artifacts match run report hashes")
    return 0, lines, artifacts, {
        "checked": checked,
        "matched": matched,
        "mismatched": mismatched,
        "missing": missing,
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Replay deterministic scoring from a run report.")
    parser.add_argument("--run-report", type=str, help="Path to run report JSON.")
    parser.add_argument("--run-id", type=str, help="Run id to locate under state/runs.")
    parser.add_argument("--run-dir", type=str, help="Run directory containing run_report.json.")
    parser.add_argument("--runs-dir", type=str, help="Base runs dir (default: state/runs).")
    parser.add_argument("--profile", type=str, default="cs", help="Profile to replay (default: cs).")
    parser.add_argument("--strict", action="store_true", help="Treat mismatches as non-zero exit.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON to stdout.")
    parser.add_argument("--quiet", action="store_true", help="Suppress non-JSON output.")
    args = parser.parse_args(argv)

    runs_dir = Path(args.runs_dir) if args.runs_dir else RUN_METADATA_DIR
    try:
        report_path = _resolve_report_path(args.run_id, args.run_report, args.run_dir, runs_dir)
    except SystemExit as exc:
        if not args.quiet and not args.json:
            print(str(exc), file=sys.stderr)
        return 2

    if not report_path.exists():
        if not args.quiet and not args.json:
            print(f"ERROR: run report not found at {report_path}", file=sys.stderr)
        return 2

    try:
        report = _load_run_report(report_path)
    except Exception as exc:
        if not args.quiet and not args.json:
            print(f"ERROR: failed to load run report: {exc!r}", file=sys.stderr)
        return 3

    exit_code, lines, artifacts, counts = _replay_report(report, args.profile, args.strict)
    if args.json:
        payload = {
            "run_id": report.get("run_id"),
            "checked": counts["checked"],
            "matched": counts["matched"],
            "mismatched": counts["mismatched"],
            "missing": counts["missing"],
            "artifacts": artifacts,
        }
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    elif not args.quiet:
        _print_report(lines)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
