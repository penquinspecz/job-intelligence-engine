#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional


def _type_ok(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return False


def _join(path: str, key: str) -> str:
    if not path:
        return key
    return f"{path}.{key}"


def _validate_node(value: Any, schema: Dict[str, Any], path: str, errors: List[str]) -> None:
    expected_type = schema.get("type")
    if expected_type and not _type_ok(value, expected_type):
        errors.append(f"{path or 'root'}: expected {expected_type}")
        return

    if expected_type == "object":
        props = schema.get("properties") or {}
        required = schema.get("required") or []
        for key in required:
            if key not in value:
                errors.append(f"{_join(path, key)}: missing required key")
        for key, sub_schema in props.items():
            if key in value:
                _validate_node(value[key], sub_schema, _join(path, key), errors)

        additional = schema.get("additionalProperties", True)
        if additional is False:
            allowed = set(props.keys())
            for key in value.keys():
                if key not in allowed:
                    errors.append(f"{_join(path, key)}: unknown key")
        elif isinstance(additional, dict):
            allowed = set(props.keys())
            for key in value.keys():
                if key not in allowed:
                    _validate_node(value[key], additional, _join(path, key), errors)

    if expected_type == "array":
        item_schema = schema.get("items")
        if item_schema:
            for idx, item in enumerate(value):
                _validate_node(item, item_schema, f"{path}[{idx}]", errors)


def _coerce_int(value: Any) -> Optional[int]:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return None


def resolve_schema_path(version: int) -> Path:
    filename = f"run_report.schema.v{version}.json"
    attempted: List[Path] = []
    override = os.environ.get("JOBINTEL_SCHEMA_DIR")
    if override:
        attempted.append(Path(override) / filename)
    attempted.append(Path(__file__).resolve().parents[1] / "schemas" / filename)
    attempted.append(Path.cwd() / "schemas" / filename)

    for candidate in attempted:
        if candidate.exists():
            return candidate

    attempted_display = ", ".join(str(p.resolve()) for p in attempted)
    raise RuntimeError(
        "Schema file not found for version "
        f"{version}. Tried: {attempted_display}. "
        "Ensure schemas are available or set JOBINTEL_SCHEMA_DIR."
    )


def _validate_delta_summary(report: Dict[str, Any], errors: List[str]) -> None:
    delta = report.get("delta_summary")
    if delta is None:
        return
    if not isinstance(delta, dict):
        errors.append("delta_summary: expected object")
        return

    provider_profile = delta.get("provider_profile")
    if not isinstance(provider_profile, dict):
        errors.append("delta_summary.provider_profile: expected object")
        return

    for provider, profiles in provider_profile.items():
        if not isinstance(profiles, dict):
            errors.append(f"delta_summary.provider_profile.{provider}: expected object")
            continue
        for profile, entry in profiles.items():
            if not isinstance(entry, dict):
                errors.append(f"delta_summary.provider_profile.{provider}.{profile}: expected object")
                continue
            path = f"delta_summary.provider_profile.{provider}.{profile}"
            counts = {
                "labeled_total": entry.get("labeled_total"),
                "ranked_total": entry.get("ranked_total"),
                "new_job_count": entry.get("new_job_count"),
                "removed_job_count": entry.get("removed_job_count"),
                "changed_job_count": entry.get("changed_job_count"),
                "unchanged_job_count": entry.get("unchanged_job_count"),
            }
            for key, value in counts.items():
                if value is not None and _coerce_int(value) is None:
                    errors.append(f"{path}.{key}: expected integer")
            change_fields = entry.get("change_fields")
            if change_fields is not None:
                if not isinstance(change_fields, dict):
                    errors.append(f"{path}.change_fields: expected object")
                else:
                    for key, value in change_fields.items():
                        if _coerce_int(value) is None:
                            errors.append(f"{path}.change_fields.{key}: expected integer")
            ranked_total = _coerce_int(counts["ranked_total"]) or 0
            new_count = _coerce_int(counts["new_job_count"]) or 0
            changed_count = _coerce_int(counts["changed_job_count"]) or 0
            unchanged_count = _coerce_int(counts["unchanged_job_count"]) or 0
            baseline_run_id = entry.get("baseline_run_id")
            if baseline_run_id is None:
                if any(value != 0 for value in (new_count, changed_count, unchanged_count)):
                    errors.append(f"{path}: baseline missing requires zero delta counts")
            else:
                if ranked_total and new_count + changed_count + unchanged_count != ranked_total:
                    errors.append(f"{path}: delta counts do not match ranked_total")


def validate_report(report: Dict[str, Any], schema: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    _validate_node(report, schema, "", errors)
    _validate_delta_summary(report, errors)
    return errors


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Validate a run report against a schema.")
    ap.add_argument("report_path", help="Path to run_report.json.")
    ap.add_argument("schema_path", help="Path to schema JSON file.")
    args = ap.parse_args(argv)

    report = json.loads(Path(args.report_path).read_text(encoding="utf-8"))
    schema = json.loads(Path(args.schema_path).read_text(encoding="utf-8"))

    errors = validate_report(report, schema)
    if errors:
        print("Schema validation failed:")
        for err in errors:
            print(f"- {err}")
        return 1
    print("Schema validation OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
