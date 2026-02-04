#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid json: {path}") from exc


def _format_bool(value: Any) -> str:
    return "true" if bool(value) else "false"


def _plan_stats(plan_doc: dict[str, Any] | None) -> tuple[int, int]:
    if not plan_doc:
        return 0, 0
    plan_items = plan_doc.get("plan")
    if not isinstance(plan_items, list):
        return 0, 0
    missing = 0
    for item in plan_items:
        if not isinstance(item, dict):
            continue
        if not item.get("sha256") or item.get("bytes") in (None, ""):
            missing += 1
    return len(plan_items), missing


def _replay_summary(run_report: dict[str, Any]) -> str:
    for key in ("replay_verification", "replay_report"):
        payload = run_report.get(key)
        if isinstance(payload, dict):
            ok = payload.get("ok")
            checked = payload.get("checked")
            mismatched = payload.get("mismatched")
            missing = payload.get("missing")
            parts = [f"replay_ok: {_format_bool(ok)}"]
            if checked is not None:
                parts.append(f"replay_checked: {checked}")
            if mismatched is not None:
                parts.append(f"replay_mismatched: {mismatched}")
            if missing is not None:
                parts.append(f"replay_missing: {missing}")
            return "\n".join(parts)
    return "replay_ok: not_present"


def extract_proof(run_report: dict[str, Any], plan_doc: dict[str, Any] | None) -> str:
    run_id = run_report.get("run_id", "unknown")
    verifiable = run_report.get("verifiable_artifacts", {})
    verifiable_count = len(verifiable) if isinstance(verifiable, dict) else 0
    config_fp = run_report.get("config_fingerprint", "unknown")
    env_fp = run_report.get("environment_fingerprint", "unknown")
    plan_count, plan_missing = _plan_stats(plan_doc)

    lines = [
        f"run_id: {run_id}",
        f"verifiable_artifacts: {verifiable_count}",
        f"config_fingerprint: {config_fp}",
        f"environment_fingerprint: {env_fp}",
        f"plan_items: {plan_count}",
        f"plan_missing_sha_or_bytes: {plan_missing}",
        _replay_summary(run_report),
    ]
    return "\n".join(lines) + "\n"


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract proof snippet from run artifacts")
    parser.add_argument("--run-report", required=True, help="Path to run_report.json")
    parser.add_argument("--plan-json", help="Optional publish plan JSON path")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    try:
        args = _parse_args(argv)
        run_report = _read_json(Path(args.run_report))
        plan_doc = _read_json(Path(args.plan_json)) if args.plan_json else None
        sys.stdout.write(extract_proof(run_report, plan_doc))
        return 0
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except Exception as exc:  # pragma: no cover - last-resort guard
        print(f"runtime error: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
