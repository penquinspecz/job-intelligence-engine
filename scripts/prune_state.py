#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from ji_engine.config import (
    DEFAULT_KEEP_HISTORY_SNAPSHOTS_PER_PROFILE,
    DEFAULT_KEEP_RUN_REPORTS,
    DEFAULT_PRUNE_MAX_AGE_DAYS,
    HISTORY_DIR,
    RUN_METADATA_DIR,
    STATE_DIR,
)


@dataclass(frozen=True)
class PruneAction:
    path: Path
    kind: str  # "file" | "dir"
    reason: str


def _is_within_state(path: Path, state_dir: Path) -> bool:
    try:
        path.resolve().relative_to(state_dir.resolve())
        return True
    except Exception:
        return False


def _parse_sanitized_run_id(value: str) -> Optional[datetime]:
    """
    Parse run ids like 20260101T000000Z into UTC datetime.
    """
    try:
        return datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _run_id_from_runs_file(path: Path) -> str:
    return path.stem


def _sorted_run_reports(runs_dir: Path) -> List[Path]:
    reports = [p for p in runs_dir.glob("*.json") if p.is_file()]
    reports.sort(key=lambda p: _run_id_from_runs_file(p))
    return reports


def _history_profile_snapshots(history_dir: Path, profile: str) -> List[Tuple[str, Path]]:
    """
    Returns list of (sanitized_run_id, profile_snapshot_dir).
    Excludes HISTORY_DIR/latest.
    """
    out: List[Tuple[str, Path]] = []
    for profile_dir in history_dir.rglob(profile):
        if "latest" in profile_dir.parts:
            continue
        if not profile_dir.is_dir():
            continue
        if profile_dir.name != profile:
            continue
        sanitized = profile_dir.parent.name
        out.append((sanitized, profile_dir))
    out.sort(key=lambda t: t[0])
    return out


def plan_prune(
    *,
    state_dir: Path = STATE_DIR,
    runs_dir: Path = RUN_METADATA_DIR,
    history_dir: Path = HISTORY_DIR,
    keep_run_reports: int = DEFAULT_KEEP_RUN_REPORTS,
    keep_history_per_profile: int = DEFAULT_KEEP_HISTORY_SNAPSHOTS_PER_PROFILE,
    max_age_days: Optional[int] = DEFAULT_PRUNE_MAX_AGE_DAYS,
    profile: Optional[str] = None,
) -> List[PruneAction]:
    if keep_run_reports < 1 or keep_history_per_profile < 1:
        raise ValueError("keep counts must be >= 1")

    actions: List[PruneAction] = []

    # Run reports retention (never delete most recent).
    reports = _sorted_run_reports(runs_dir)
    if reports:
        newest = reports[-1]
        keep_set = set(reports[max(0, len(reports) - keep_run_reports) :])
        keep_set.add(newest)

        cutoff: Optional[datetime] = None
        if max_age_days is not None and max_age_days > 0:
            cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)

        for p in reports:
            if p == newest:
                continue
            run_dt = _parse_sanitized_run_id(_run_id_from_runs_file(p))
            age_delete = bool(cutoff and run_dt and run_dt < cutoff)
            count_delete = p not in keep_set
            if age_delete or count_delete:
                reason = "age" if age_delete else "count"
                actions.append(PruneAction(path=p, kind="file", reason=f"runs:{reason}"))

    # History retention per profile (never delete latest snapshot for each profile).
    profiles: List[str] = []
    latest_dir = history_dir / "latest"
    if latest_dir.exists():
        for p in sorted(latest_dir.iterdir()):
            if p.is_dir():
                profiles.append(p.name)
    else:
        # Fallback: discover profiles from history tree.
        for p in history_dir.glob("*/*/*"):
            if p.is_dir() and p.parent.name != "latest":
                profiles.append(p.name)
        profiles = sorted(set(profiles))

    cutoff_hist: Optional[datetime] = None
    if max_age_days is not None and max_age_days > 0:
        cutoff_hist = datetime.now(timezone.utc) - timedelta(days=max_age_days)

    selected_profiles = [profile] if profile else profiles
    for profile_name in selected_profiles:
        snapshots = _history_profile_snapshots(history_dir, profile_name)
        if not snapshots:
            continue
        newest_run_id, newest_path = snapshots[-1]
        keep_by_count = set(snapshots[max(0, len(snapshots) - keep_history_per_profile) :])
        keep_by_count.add((newest_run_id, newest_path))

        for run_id, path in snapshots:
            if path == newest_path:
                continue
            run_dt = _parse_sanitized_run_id(run_id)
            age_delete = bool(cutoff_hist and run_dt and run_dt < cutoff_hist)
            count_delete = (run_id, path) not in keep_by_count
            if age_delete or count_delete:
                reason = "age" if age_delete else "count"
                actions.append(PruneAction(path=path, kind="dir", reason=f"history:{profile_name}:{reason}"))

    # Deterministic output ordering
    actions.sort(key=lambda a: (a.kind, str(a.path)))

    # Safety: only allow deletions under state_dir
    safe_actions: List[PruneAction] = []
    for a in actions:
        if _is_within_state(a.path, state_dir):
            safe_actions.append(a)
    return safe_actions


def apply_prune(actions: Iterable[PruneAction], *, state_dir: Path = STATE_DIR) -> None:
    for a in actions:
        if not _is_within_state(a.path, state_dir):
            raise RuntimeError(f"Refusing to delete outside state/: {a.path}")
        if a.kind == "file":
            a.path.unlink(missing_ok=True)
        elif a.kind == "dir":
            if a.path.exists():
                shutil.rmtree(a.path)
        else:
            raise RuntimeError(f"Unknown prune action kind: {a.kind}")


def _print_actions(actions: List[PruneAction]) -> None:
    if not actions:
        print("Nothing to prune.")
        return
    for a in actions:
        print(f"DELETE {a.kind} {a.path} ({a.reason})")


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Prune state history/run reports with deterministic retention.")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="Print what would be deleted.")
    mode.add_argument("--apply", action="store_true", help="Delete selected files/directories.")
    ap.add_argument("--keep-runs", type=int, default=DEFAULT_KEEP_RUN_REPORTS)
    ap.add_argument("--keep-history", type=int, default=DEFAULT_KEEP_HISTORY_SNAPSHOTS_PER_PROFILE)
    ap.add_argument("--max-age-days", type=int, default=DEFAULT_PRUNE_MAX_AGE_DAYS)
    ap.add_argument("--profile", help="Limit history pruning to a single profile.")
    args = ap.parse_args(argv)

    state_dir = Path(os.environ.get("JOBINTEL_STATE_DIR") or str(STATE_DIR)).expanduser()
    runs_dir = state_dir / "runs"
    history_dir = state_dir / "history"

    if not state_dir.exists():
        print(f"ERROR: state dir not found: {state_dir}", file=sys.stderr)
        return 2

    try:
        actions = plan_prune(
            state_dir=state_dir,
            runs_dir=runs_dir,
            history_dir=history_dir,
            keep_run_reports=int(args.keep_runs),
            keep_history_per_profile=int(args.keep_history),
            max_age_days=int(args.max_age_days) if args.max_age_days is not None else None,
            profile=args.profile,
        )
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"ERROR: {exc!r}", file=sys.stderr)
        return 3

    _print_actions(actions)
    if args.apply:
        try:
            apply_prune(actions, state_dir=state_dir)
        except Exception as exc:
            print(f"ERROR: {exc!r}", file=sys.stderr)
            return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
