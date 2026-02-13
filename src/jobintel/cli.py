"""
SignalCraft
Copyright (c) 2026 Chris Menendez.
All Rights Reserved.
See LICENSE for permitted use.
"""

from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional

from ji_engine.providers.openai_provider import CAREERS_SEARCH_URL
from ji_engine.providers.registry import load_providers_config, resolve_provider_ids

from .safety.diff import build_safety_diff_report, load_jobs_from_path, render_summary, write_report
from .snapshots.refresh import refresh_snapshot
from .snapshots.validate import MIN_BYTES_DEFAULT, validate_snapshots

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROVIDERS_CONFIG = REPO_ROOT / "config" / "providers.json"


def _setup_logging() -> None:
    if logging.getLogger().hasHandlers():
        return
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def _load_provider_map(path: Path) -> Dict[str, dict]:
    providers = load_providers_config(path)
    return {p["provider_id"]: p for p in providers}


def _fallback_provider(provider_id: str) -> Optional[dict]:
    if provider_id != "openai":
        return None
    return {
        "provider_id": "openai",
        "careers_url": CAREERS_SEARCH_URL,
        "snapshot_path": str(REPO_ROOT / "data" / "openai_snapshots" / "index.html"),
    }


def _resolve_providers(provider_arg: str, providers_config: Path) -> List[dict]:
    provider_arg = provider_arg.lower().strip()
    provider_map = _load_provider_map(providers_config) if providers_config.exists() else {}

    if provider_arg == "all":
        return [provider_map[key] for key in sorted(provider_map.keys())]

    if provider_arg in provider_map:
        return [provider_map[provider_arg]]

    fallback = _fallback_provider(provider_arg)
    if fallback:
        return [fallback]

    raise SystemExit(f"Unknown provider '{provider_arg}'.")


def _refresh_snapshots(args: argparse.Namespace) -> int:
    _setup_logging()

    providers_config = Path(args.providers_config)
    if args.provider == "all" and args.out:
        raise SystemExit("--out cannot be used with --provider all")
    if not args.out:
        raise SystemExit("--out is required for snapshot writes; use an explicit output path.")

    targets = _resolve_providers(args.provider, providers_config)
    status = 0
    for provider in targets:
        provider_id = provider["provider_id"]
        url = provider.get("careers_url") or provider.get("board_url") or CAREERS_SEARCH_URL
        out_path = Path(args.out)
        fetch_method = (args.fetch or os.environ.get("JOBINTEL_SNAPSHOT_FETCH") or "requests").lower()
        extraction_mode = provider.get("extraction_mode") or provider.get("type")

        try:
            exit_code = refresh_snapshot(
                provider_id,
                url,
                out_path,
                force=args.force,
                timeout=args.timeout,
                min_bytes=args.min_bytes,
                fetch_method=fetch_method,
                headers={"User-Agent": args.user_agent},
                extraction_mode=extraction_mode,
            )
        except RuntimeError as exc:
            raise SystemExit(str(exc)) from exc
        if exit_code != 0:
            status = exit_code
    return status


def _validate_snapshots(args: argparse.Namespace) -> int:
    providers_config = Path(args.providers_config)
    providers_cfg = load_providers_config(providers_config)
    if args.all:
        provider_ids: List[str] = []
    else:
        provider_arg = (args.provider or "openai").lower().strip()
        if provider_arg == "all":
            raise SystemExit("Use --all to validate discovered snapshots.")
        try:
            provider_ids = resolve_provider_ids(provider_arg, providers_cfg, default_provider="openai")
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc

    results = validate_snapshots(
        providers_cfg,
        provider_ids=provider_ids,
        validate_all=args.all,
        data_dir=Path(args.data_dir) if args.data_dir else None,
    )
    failures = [result for result in results if not result.ok]
    for result in results:
        if result.skipped:
            status = "SKIP"
        else:
            status = "OK" if result.ok else "FAIL"
        print(f"[snapshots] {status} {result.provider}: {result.path} ({result.reason})")

    if failures:
        print("Snapshot validation failed:")
        for result in failures:
            print(f"- {result.provider}: {result.path} ({result.reason})")
        return 1
    return 0


def _split_csv(value: Optional[str]) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _merge_profiles(args: argparse.Namespace) -> list[str]:
    profiles = []
    profiles.extend(_split_csv(args.profiles))
    profiles.extend(_split_csv(args.role))
    seen = set()
    ordered = []
    for profile in profiles:
        if profile in seen:
            continue
        seen.add(profile)
        ordered.append(profile)
    return ordered


def _run_daily(args: argparse.Namespace) -> int:
    _setup_logging()

    profiles = _merge_profiles(args)
    if not profiles:
        raise SystemExit("No profiles provided. Use --role or --profiles.")

    cmd = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "run_daily.py"),
        "--profiles",
        ",".join(profiles),
    ]
    if args.providers:
        cmd.extend(["--providers", args.providers])
    if args.offline:
        cmd.append("--offline")
    if args.no_post:
        cmd.append("--no_post")
    if args.no_enrich:
        cmd.append("--no_enrich")
    if args.ai:
        cmd.append("--ai")
    if args.ai_only:
        cmd.append("--ai_only")

    env = os.environ.copy()
    if args.offline:
        env["CAREERS_MODE"] = "SNAPSHOT"

    logging.info("Running: %s", " ".join(cmd))
    result = subprocess.run(cmd, env=env, check=False)
    return result.returncode


def _safety_diff(args: argparse.Namespace) -> int:
    baseline_path = Path(args.baseline)
    candidate_path = Path(args.candidate)
    baseline_jobs = load_jobs_from_path(
        baseline_path,
        provider=args.provider,
        profile=args.profile,
    )
    candidate_jobs = load_jobs_from_path(
        candidate_path,
        provider=args.provider,
        profile=args.profile,
    )
    report = build_safety_diff_report(
        baseline_jobs,
        candidate_jobs,
        baseline_path=str(baseline_path),
        candidate_path=str(candidate_path),
        top_n=args.top,
    )
    report_path = Path(args.report_out)
    write_report(report, report_path)
    print(render_summary(report))
    print(f"Report written to {report_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="jobintel",
        description="SignalCraft CLI (Job Intelligence Engine, JIE).",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    snapshots = subparsers.add_parser("snapshots", help="Snapshot maintenance")
    snapshots_sub = snapshots.add_subparsers(dest="snapshots_command", required=True)

    refresh = snapshots_sub.add_parser("refresh", help="Refresh provider snapshots")
    refresh.add_argument("--provider", required=True, help="Provider id or 'all'.")
    refresh.add_argument("--out", help="Output snapshot path (required).")
    refresh.add_argument("--force", action="store_true", help="Write snapshot even if validation fails.")
    refresh.add_argument("--fetch", choices=["requests", "playwright"], default="requests")
    refresh.add_argument("--timeout", type=float, default=20.0)
    refresh.add_argument("--min-bytes", type=int, default=MIN_BYTES_DEFAULT)
    refresh.add_argument("--user-agent", default="signalcraft/0.1 (+snapshot-refresh)")
    refresh.add_argument(
        "--providers-config",
        default=str(DEFAULT_PROVIDERS_CONFIG),
        help="Path to providers config JSON.",
    )
    refresh.set_defaults(func=_refresh_snapshots)

    validate_cmd = snapshots_sub.add_parser("validate", help="Validate provider snapshots")
    validate_cmd.add_argument("--provider", help="Provider id to validate (default: openai).")
    validate_cmd.add_argument("--all", action="store_true", help="Validate all known providers.")
    validate_cmd.add_argument("--data-dir", help="Base data directory (default: JOBINTEL_DATA_DIR or data).")
    validate_cmd.add_argument(
        "--providers-config",
        default=str(DEFAULT_PROVIDERS_CONFIG),
        help="Path to providers config JSON.",
    )
    validate_cmd.set_defaults(func=_validate_snapshots)

    run_cmd = subparsers.add_parser("run", help="Run pipeline helpers")
    run_cmd.add_argument("--role", help="Profile role name (e.g. cs).")
    run_cmd.add_argument("--profiles", help="Comma-separated profiles (e.g. cs or cs,tam,se).")
    run_cmd.add_argument("--providers", help="Comma-separated provider ids.")
    run_cmd.add_argument("--offline", action="store_true", help="Force snapshot mode (no live scraping).")
    run_cmd.add_argument("--no_post", "--no-post", dest="no_post", action="store_true")
    run_cmd.add_argument("--no_enrich", "--no-enrich", dest="no_enrich", action="store_true")
    run_cmd.add_argument("--ai", action="store_true")
    run_cmd.add_argument("--ai_only", action="store_true")
    run_cmd.set_defaults(func=_run_daily)

    safety_cmd = subparsers.add_parser("safety", help="Semantic safety net tooling")
    safety_sub = safety_cmd.add_subparsers(dest="safety_command", required=True)

    diff_cmd = safety_sub.add_parser("diff", help="Compare baseline vs candidate job outputs")
    diff_cmd.add_argument("--baseline", required=True, help="Baseline run or jobs JSON path.")
    diff_cmd.add_argument("--candidate", required=True, help="Candidate run or jobs JSON path.")
    diff_cmd.add_argument("--provider", help="Provider id when using run reports with multiple providers.")
    diff_cmd.add_argument("--profile", help="Profile name when using run reports with multiple profiles.")
    diff_cmd.add_argument("--top", type=int, default=5, help="Top N changed records to include.")
    diff_cmd.add_argument(
        "--report-out",
        default="safety_diff_report.json",
        help="Output path for JSON report.",
    )
    diff_cmd.set_defaults(func=_safety_diff)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
