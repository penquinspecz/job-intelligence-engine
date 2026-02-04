#!/usr/bin/env python3
from __future__ import annotations

try:
    import _bootstrap  # type: ignore
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ji_engine.config import DATA_DIR, RUN_METADATA_DIR, STATE_DIR
from ji_engine.utils.verification import compute_sha256_file, verify_verifiable_artifacts


def _sanitize_run_id(run_id: str) -> str:
    return run_id.replace(":", "").replace("-", "").replace(".", "")


def _load_run_report(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _resolve_archived_path(path_str: Optional[str], state_dir: Path) -> Optional[str]:
    if not path_str:
        return None
    path = Path(path_str)
    if path.is_absolute():
        return str(path)
    return str(state_dir / path)


def _resolve_provider(report: Dict[str, Any]) -> str:
    providers = report.get("providers") or []
    if isinstance(providers, list) and providers:
        if "openai" in providers:
            return "openai"
        if isinstance(providers[0], str):
            return providers[0]
    return "openai"


def _resolve_archived_inputs(
    report: Dict[str, Any], provider: str, profile: str, state_dir: Path
) -> Tuple[Optional[Path], Optional[Path]]:
    archived = report.get("archived_inputs_by_provider_profile") or {}
    if not isinstance(archived, dict):
        return None, None
    by_provider = archived.get(provider)
    if not isinstance(by_provider, dict):
        return None, None
    by_profile = by_provider.get(profile)
    if not isinstance(by_profile, dict):
        return None, None
    selected = by_profile.get("selected_scoring_input")
    profile_cfg = by_profile.get("profile_config")
    if not isinstance(selected, dict) or not isinstance(profile_cfg, dict):
        return None, None
    selected_path = _resolve_archived_path(selected.get("archived_path"), state_dir)
    profile_path = _resolve_archived_path(profile_cfg.get("archived_path"), state_dir)
    return (Path(selected_path) if selected_path else None, Path(profile_path) if profile_path else None)


def _resolve_expected_outputs(
    report: Dict[str, Any], provider: str, profile: str
) -> Dict[str, Dict[str, Optional[str]]]:
    outputs_by_provider = report.get("outputs_by_provider") or {}
    if isinstance(outputs_by_provider, dict):
        provider_payload = outputs_by_provider.get(provider)
        if isinstance(provider_payload, dict):
            profile_payload = provider_payload.get(profile)
            if isinstance(profile_payload, dict):
                return profile_payload
    outputs_by_profile = report.get("outputs_by_profile") or {}
    if isinstance(outputs_by_profile, dict):
        profile_payload = outputs_by_profile.get(profile)
        if isinstance(profile_payload, dict):
            return profile_payload
    return {}


def _collect_archived_entries(
    report: Dict[str, Any], profile: str, state_dir: Path
) -> List[Tuple[str, Optional[str], Optional[str]]]:
    archived = report.get("archived_inputs_by_provider_profile") or {}
    if not isinstance(archived, dict):
        return []
    providers = report.get("providers") or []
    provider = "openai"
    if isinstance(providers, list) and providers:
        provider = "openai" if "openai" in providers else providers[0]
    by_provider = archived.get(provider)
    if not isinstance(by_provider, dict):
        return []
    by_profile = by_provider.get(profile)
    if not isinstance(by_profile, dict):
        return []
    entries: List[Tuple[str, Optional[str], Optional[str]]] = []
    for key in ("selected_scoring_input", "profile_config"):
        meta = by_profile.get(key)
        if isinstance(meta, dict):
            entries.append(
                (
                    f"archived_input:{key}",
                    _resolve_archived_path(meta.get("archived_path"), state_dir),
                    meta.get("sha256"),
                )
            )
    return entries


def _collect_entries(
    report: Dict[str, Any], profile: str, state_dir: Path
) -> List[Tuple[str, Optional[str], Optional[str]]]:
    entries: List[Tuple[str, Optional[str], Optional[str]]] = []

    archived_entries = _collect_archived_entries(report, profile, state_dir)
    if archived_entries:
        entries.extend(archived_entries)
        return entries

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
    report: Dict[str, Any], profile: str, strict: bool, state_dir: Path
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

    entries = _collect_entries(report, profile, state_dir)
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
        return (
            2,
            ["FAIL: no inputs/outputs to verify in run report"],
            artifacts,
            {
                "checked": 0,
                "matched": 0,
                "mismatched": 0,
                "missing": 0,
            },
        )

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
        return (
            (2 if strict else 0),
            lines,
            artifacts,
            {
                "checked": checked,
                "matched": matched,
                "mismatched": mismatched,
                "missing": missing,
            },
        )
    if mismatched > 0:
        lines.insert(0, "FAIL: mismatched artifacts")
        return (
            (2 if strict else 0),
            lines,
            artifacts,
            {
                "checked": checked,
                "matched": matched,
                "mismatched": mismatched,
                "missing": missing,
            },
        )
    lines.insert(0, "PASS: all artifacts match run report hashes")
    return (
        0,
        lines,
        artifacts,
        {
            "checked": checked,
            "matched": matched,
            "mismatched": mismatched,
            "missing": missing,
        },
    )


def _recalc_report(
    report: Dict[str, Any], profile: str, strict: bool, run_dir: Path, quiet: bool, state_dir: Path
) -> Tuple[int, List[str], Dict[str, Dict[str, Optional[object]]], Dict[str, int], List[str], List[str]]:
    lines: List[str] = []
    artifacts: Dict[str, Dict[str, Optional[object]]] = {}
    mismatched_keys: List[str] = []
    missing_keys: List[str] = []

    provider = _resolve_provider(report)
    selected_input, profile_cfg = _resolve_archived_inputs(report, provider, profile, state_dir)
    if not selected_input or not profile_cfg:
        return (
            2,
            ["FAIL: archived inputs missing for recalc"],
            artifacts,
            {
                "checked": 0,
                "matched": 0,
                "mismatched": 0,
                "missing": 0,
            },
            mismatched_keys,
            missing_keys,
        )

    expected_outputs = _resolve_expected_outputs(report, provider, profile)
    if not expected_outputs:
        return (
            2,
            ["FAIL: expected outputs missing for recalc"],
            artifacts,
            {
                "checked": 0,
                "matched": 0,
                "mismatched": 0,
                "missing": 0,
            },
            mismatched_keys,
            missing_keys,
        )

    recalc_dir = run_dir / "_recalc" / provider / profile
    if recalc_dir.exists():
        shutil.rmtree(recalc_dir)
    recalc_dir.mkdir(parents=True, exist_ok=True)

    out_json = recalc_dir / f"{provider}_ranked_jobs.{profile}.json"
    out_csv = recalc_dir / f"{provider}_ranked_jobs.{profile}.csv"
    out_families = recalc_dir / f"{provider}_ranked_families.{profile}.json"
    out_md = recalc_dir / f"{provider}_shortlist.{profile}.md"
    out_top = recalc_dir / f"{provider}_top.{profile}.md"

    flags = report.get("flags") or {}
    min_score = flags.get("min_score", 40)
    us_only = bool(flags.get("us_only", False))

    try:
        import scripts.score_jobs as score_jobs  # local import to avoid side-effects when not recalc

        argv = [
            "score_jobs.py",
            "--profile",
            profile,
            "--profiles",
            str(profile_cfg),
            "--in_path",
            str(selected_input),
            "--out_json",
            str(out_json),
            "--out_csv",
            str(out_csv),
            "--out_families",
            str(out_families),
            "--out_md",
            str(out_md),
            "--out_md_top_n",
            str(out_top),
            "--min_score",
            str(min_score),
        ]
        if us_only:
            argv.append("--us_only")
        import contextlib
        import io

        old_argv = sys.argv
        sys.argv = argv
        try:
            if quiet:
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    score_jobs.main()
            else:
                score_jobs.main()
        finally:
            sys.argv = old_argv
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 3
        return (
            max(3, code),
            [f"FAIL: recalc failed ({exc})"],
            artifacts,
            {
                "checked": 0,
                "matched": 0,
                "mismatched": 0,
                "missing": 0,
            },
            mismatched_keys,
            missing_keys,
        )
    except Exception as exc:
        return (
            3,
            [f"FAIL: recalc failed ({exc!r})"],
            artifacts,
            {
                "checked": 0,
                "matched": 0,
                "mismatched": 0,
                "missing": 0,
            },
            mismatched_keys,
            missing_keys,
        )

    output_paths = {
        "ranked_json": out_json,
        "ranked_csv": out_csv,
        "ranked_families_json": out_families,
        "shortlist_md": out_md,
        "top_md": out_top,
    }

    checked = 0
    matched = 0
    mismatched = 0
    missing = 0

    lines.append("RECALC REPORT")
    for key, meta in sorted(expected_outputs.items()):
        if not isinstance(meta, dict):
            continue
        expected_hash = meta.get("sha256")
        output_path = output_paths.get(key)
        checked += 1
        if not output_path or not output_path.exists() or not expected_hash:
            missing += 1
            missing_keys.append(key)
            artifacts[key] = {
                "path": str(output_path) if output_path else None,
                "expected": expected_hash,
                "actual": None,
                "bytes": None,
                "match": False,
                "missing": True,
            }
            lines.append(f"recalc:{key}: expected={expected_hash} actual=None match=False")
            continue
        actual_hash = compute_sha256_file(output_path)
        ok = actual_hash == expected_hash
        if ok:
            matched += 1
        else:
            mismatched += 1
            mismatched_keys.append(key)
        artifacts[key] = {
            "path": str(output_path),
            "expected": expected_hash,
            "actual": actual_hash,
            "bytes": output_path.stat().st_size,
            "match": ok,
            "missing": False,
        }
        lines.append(f"recalc:{key}: expected={expected_hash} actual={actual_hash} match={str(ok)}")

    lines.append(f"SUMMARY: checked={checked} matched={matched} mismatched={mismatched} missing={missing}")
    if missing > 0:
        lines.insert(0, "FAIL: missing recalc artifacts")
        return (
            (2 if strict else 0),
            lines,
            artifacts,
            {
                "checked": checked,
                "matched": matched,
                "mismatched": mismatched,
                "missing": missing,
            },
            mismatched_keys,
            missing_keys,
        )
    if mismatched > 0:
        lines.insert(0, "FAIL: recalc mismatched artifacts")
        return (
            (2 if strict else 0),
            lines,
            artifacts,
            {
                "checked": checked,
                "matched": matched,
                "mismatched": mismatched,
                "missing": missing,
            },
            mismatched_keys,
            missing_keys,
        )
    lines.insert(0, "PASS: recalc outputs match run report hashes")
    return (
        0,
        lines,
        artifacts,
        {
            "checked": checked,
            "matched": matched,
            "mismatched": mismatched,
            "missing": missing,
        },
        mismatched_keys,
        missing_keys,
    )


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Replay deterministic scoring from a run report.")
    parser.add_argument("--run-report", type=str, help="Path to run report JSON.")
    parser.add_argument("--run-id", type=str, help="Run id to locate under state/runs.")
    parser.add_argument("--run-dir", type=str, help="Run directory containing run_report.json.")
    parser.add_argument("--runs-dir", type=str, help="Base runs dir (default: state/runs).")
    parser.add_argument("--profile", type=str, default="cs", help="Profile to replay (default: cs).")
    parser.add_argument("--strict", action="store_true", help="Treat mismatches as non-zero exit.")
    parser.add_argument("--recalc", action="store_true", help="Recompute scoring outputs from archived inputs.")
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

    if args.run_dir:
        run_dir = Path(args.run_dir)
    elif report_path.name == "run_report.json":
        run_dir = report_path.parent
    else:
        run_id = report.get("run_id")
        run_dir = RUN_METADATA_DIR / _sanitize_run_id(run_id or report_path.stem)
    state_dir = STATE_DIR
    if run_dir.parent.name == "runs":
        state_dir = run_dir.parent.parent

    if args.recalc:
        (
            exit_code,
            lines,
            artifacts,
            counts,
            recalc_mismatched,
            recalc_missing,
        ) = _recalc_report(report, args.profile, args.strict, run_dir, args.json or args.quiet, state_dir)
    else:
        exit_code, lines, artifacts, counts = _replay_report(report, args.profile, args.strict, state_dir)
        recalc_mismatched = []
        recalc_missing = []
    if args.json:
        payload = {
            "run_id": report.get("run_id"),
            "checked": counts["checked"],
            "matched": counts["matched"],
            "mismatched": counts["mismatched"],
            "missing": counts["missing"],
            "artifacts": artifacts,
            "recalc": bool(args.recalc),
            "regenerated_artifacts": artifacts if args.recalc else {},
            "recalc_mismatched_keys": recalc_mismatched,
            "recalc_missing_keys": recalc_missing,
        }
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    elif not args.quiet:
        _print_report(lines)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
