#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
import os
from typing import Any, List

from scripts.schema_validate import validate_report


SMOKE_CONTRACT_VERSION = 1


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"Failed to read {path}: {exc}") from exc


def _count_csv_rows(path: Path) -> int:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        rows = list(reader)
    if not rows:
        return 0
    return max(len(rows) - 1, 0)


def _require_file(path: Path) -> None:
    if not path.exists():
        raise RuntimeError(f"Missing required file: {path}")
    if path.stat().st_size == 0:
        raise RuntimeError(f"Empty required file: {path}")


def _validate_delta_summary(
    report: dict,
    providers: List[str],
    profiles: List[str],
    artifacts: Path,
) -> None:
    delta_summary = report.get("delta_summary")
    if not isinstance(delta_summary, dict):
        raise RuntimeError("run_report.json missing delta_summary")

    provider_profile = delta_summary.get("provider_profile")
    if not isinstance(provider_profile, dict):
        raise RuntimeError("delta_summary.provider_profile missing or invalid")

    for provider in providers:
        provider_map = provider_profile.get(provider)
        if not isinstance(provider_map, dict):
            raise RuntimeError(f"delta_summary.provider_profile missing provider={provider}")
        for profile in profiles:
            entry = provider_map.get(profile)
            if not isinstance(entry, dict):
                raise RuntimeError(f"delta_summary missing entry for {provider}/{profile}")

            labeled_path = artifacts / f"{provider}_labeled_jobs.json"
            if provider == "openai":
                labeled_path = artifacts / "openai_labeled_jobs.json"
            labeled_jobs = _load_json(labeled_path)
            if not isinstance(labeled_jobs, list):
                raise RuntimeError(f"{labeled_path.name} must be a list")

            ranked_path = artifacts / f"{provider}_ranked_jobs.{profile}.json"
            if provider == "openai":
                ranked_path = artifacts / f"openai_ranked_jobs.{profile}.json"
            ranked_jobs = _load_json(ranked_path)
            if not isinstance(ranked_jobs, list):
                raise RuntimeError(f"{ranked_path.name} must be a list")

            if entry.get("labeled_total") != len(labeled_jobs):
                raise RuntimeError(
                    f"delta_summary labeled_total mismatch for {provider}/{profile}: "
                    f"report={entry.get('labeled_total')} labeled_jobs={len(labeled_jobs)}"
                )
            if entry.get("ranked_total") != len(ranked_jobs):
                raise RuntimeError(
                    f"delta_summary ranked_total mismatch for {provider}/{profile}: "
                    f"report={entry.get('ranked_total')} ranked_jobs={len(ranked_jobs)}"
                )

            baseline_id = entry.get("baseline_run_id")
            new_count = int(entry.get("new_job_count", 0))
            removed_count = int(entry.get("removed_job_count", 0))
            changed_count = int(entry.get("changed_job_count", 0))
            unchanged_count = int(entry.get("unchanged_job_count", 0))
            change_fields = entry.get("change_fields") or {}
            field_sum = sum(int(change_fields.get(key, 0)) for key in ("title", "location", "team", "url"))

            if baseline_id is None:
                if any(val != 0 for val in (new_count, removed_count, changed_count, unchanged_count, field_sum)):
                    raise RuntimeError(
                        f"delta_summary expected zero counts for baseline-missing {provider}/{profile}"
                    )
            else:
                if new_count + changed_count + unchanged_count != len(ranked_jobs):
                    raise RuntimeError(
                        f"delta_summary counts do not match ranked_total for {provider}/{profile}: "
                        f"new+changed+unchanged={new_count + changed_count + unchanged_count} ranked_total={len(ranked_jobs)}"
                    )
                if field_sum < changed_count:
                    raise RuntimeError(
                        f"delta_summary change_fields sum {field_sum} < changed_job_count {changed_count} "
                        f"for {provider}/{profile}"
                    )

def _validate_run_report(
    report: dict,
    providers: List[str],
    profiles: List[str],
    min_ranked: int,
    artifacts: Path,
) -> None:
    report_providers = report.get("providers") or []
    for provider in providers:
        if provider not in report_providers:
            raise RuntimeError(f"run_report.json missing provider={provider}")

    selection = report.get("selection") or {}
    provenance = selection.get("scrape_provenance") or report.get("provenance_by_provider") or {}
    classified_by_provider = selection.get("classified_job_count_by_provider")
    if not isinstance(classified_by_provider, dict):
        tried = ["selection.classified_job_count_by_provider"]
        keys = sorted(report.keys())
        raise RuntimeError(
            "run_report.json missing classified_job_count_by_provider "
            f"(tried {', '.join(tried)}; top-level keys: {', '.join(keys)})"
        )

    for provider in providers:
        meta = provenance.get(provider) or {}
        scrape_mode = (meta.get("scrape_mode") or "").lower()
        if scrape_mode != "snapshot":
            raise RuntimeError(
                f"run_report.json scrape_mode expected SNAPSHOT for {provider}, got {scrape_mode or 'missing'}"
            )

        labeled_path = artifacts / f"{provider}_labeled_jobs.json"
        if provider == "openai":
            labeled_path = artifacts / "openai_labeled_jobs.json"
        _require_file(labeled_path)

        labeled_jobs = _load_json(labeled_path)
        if not isinstance(labeled_jobs, list) or not labeled_jobs:
            raise RuntimeError(f"{labeled_path.name} must be a non-empty list")

        if provider not in classified_by_provider:
            raise RuntimeError(
                f"run_report.json missing classified_job_count_by_provider.{provider}"
            )
        if int(classified_by_provider[provider]) != len(labeled_jobs):
            raise RuntimeError(
                f"classified_job_count mismatch for {provider}: "
                f"report={classified_by_provider[provider]} labeled_jobs={len(labeled_jobs)}"
            )

        for profile in profiles:
            ranked_json_path = artifacts / f"{provider}_ranked_jobs.{profile}.json"
            ranked_csv_path = artifacts / f"{provider}_ranked_jobs.{profile}.csv"
            if provider == "openai":
                ranked_json_path = artifacts / f"openai_ranked_jobs.{profile}.json"
                ranked_csv_path = artifacts / f"openai_ranked_jobs.{profile}.csv"
            _require_file(ranked_json_path)
            _require_file(ranked_csv_path)

            ranked_jobs = _load_json(ranked_json_path)
            if not isinstance(ranked_jobs, list):
                raise RuntimeError(f"{ranked_json_path.name} must be a list")
            if len(ranked_jobs) < min_ranked:
                raise RuntimeError(
                    f"{ranked_json_path.name} has {len(ranked_jobs)} items (min {min_ranked})"
                )

            csv_rows = _count_csv_rows(ranked_csv_path)
            if csv_rows != len(ranked_jobs):
                raise RuntimeError(
                    f"{ranked_csv_path.name} rows {csv_rows} != ranked JSON length {len(ranked_jobs)}"
                )


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Validate deterministic smoke artifacts.")
    ap.add_argument("artifacts_dir", help="Path to smoke_artifacts directory.")
    ap.add_argument("--min-ranked", type=int, default=5, help="Minimum ranked jobs required.")
    ap.add_argument("--providers", default="openai", help="Comma-separated provider ids.")
    ap.add_argument("--profiles", default="cs", help="Comma-separated profiles.")
    ap.add_argument(
        "--min-schema-version",
        type=int,
        default=int(os.environ.get("SMOKE_MIN_SCHEMA_VERSION", "1")),
        help="Minimum acceptable run_report schema version.",
    )
    ap.add_argument(
        "--require-schema-version",
        type=int,
        default=int(os.environ.get("SMOKE_REQUIRE_SCHEMA_VERSION", "1")),
        help="Require exact run_report schema version (set to 0 to disable exact match).",
    )
    args = ap.parse_args(argv)

    artifacts = Path(args.artifacts_dir)
    providers = [p.strip() for p in args.providers.split(",") if p.strip()]
    profiles = [p.strip() for p in args.profiles.split(",") if p.strip()]
    if not providers:
        raise RuntimeError("No providers specified for smoke contract check")
    if not profiles:
        raise RuntimeError("No profiles specified for smoke contract check")
    run_report_path = artifacts / "run_report.json"

    _require_file(run_report_path)

    run_report = _load_json(run_report_path)
    if not isinstance(run_report, dict):
        raise RuntimeError("run_report.json must be an object")
    schema_version = run_report.get("run_report_schema_version")
    if not isinstance(schema_version, int):
        raise RuntimeError("run_report.json missing run_report_schema_version")
    if schema_version < SMOKE_CONTRACT_VERSION:
        raise RuntimeError(
            f"run_report_schema_version {schema_version} < smoke_contract_version {SMOKE_CONTRACT_VERSION}"
        )
    if args.require_schema_version:
        if schema_version != args.require_schema_version:
            raise RuntimeError(
                f"run_report_schema_version {schema_version} != required {args.require_schema_version}"
            )
    elif schema_version < args.min_schema_version:
        raise RuntimeError(
            f"run_report_schema_version {schema_version} < minimum {args.min_schema_version}"
        )

    schema_path = Path(__file__).resolve().parents[1] / "schemas" / f"run_report.schema.v{schema_version}.json"
    if not schema_path.exists():
        raise RuntimeError(f"Missing schema file: {schema_path}")
    schema = _load_json(schema_path)
    if not isinstance(schema, dict):
        raise RuntimeError(f"Schema file is not an object: {schema_path}")
    schema_errors = validate_report(run_report, schema)
    if schema_errors:
        msg = "; ".join(schema_errors[:6])
        raise RuntimeError(f"run_report.json failed schema validation: {msg}")
    _validate_run_report(run_report, providers, profiles, args.min_ranked, artifacts)
    _validate_delta_summary(run_report, providers, profiles, artifacts)

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"smoke_contract_check: {exc}")
        raise SystemExit(1)
