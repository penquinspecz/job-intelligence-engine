#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from ji_engine.config import HISTORY_DIR, USER_STATE_DIR
from ji_engine.utils.job_identity import job_identity
from ji_engine.utils.user_state import load_user_state
import scripts.run_daily as run_daily


def _list_runs(profile: str) -> List[Dict[str, object]]:
    runs_by_id: Dict[str, Dict[str, object]] = {}

    for profile_dir in HISTORY_DIR.rglob(profile):
        if "latest" in profile_dir.parts:
            continue
        if profile_dir.name != profile:
            continue
        if not profile_dir.is_dir():
            continue
        for meta_path in sorted(profile_dir.glob("*.json")):
            if meta_path.name == "run_summary.txt":
                continue
            data = json.loads(meta_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                continue
            run_id = data.get("run_id")
            if not run_id:
                continue
            if run_id in runs_by_id:
                continue
            profiles = data.get("profiles") or []
            if profile not in profiles:
                continue
            runs_by_id[run_id] = data

    return [runs_by_id[run_id] for run_id in sorted(runs_by_id)]


def _select_run(profile: str, run_id: str | None) -> Dict[str, object]:
    runs = _list_runs(profile)
    if not runs:
        raise SystemExit(1)
    if run_id:
        for entry in runs:
            if entry["run_id"] == run_id:
                return entry
        raise SystemExit(f"run_id {run_id} not found for profile {profile}")
    return runs[-1]


def _get_previous_run(profile: str, current_run_id: str) -> Dict[str, object] | None:
    runs = _list_runs(profile)
    for idx, entry in enumerate(runs):
        if entry["run_id"] == current_run_id and idx > 0:
            return runs[idx - 1]
    return None


def _history_dir_for(run_id: str, profile: str) -> Path:
    return run_daily._history_run_dir(run_id, profile)


def _load_ranked(run_id: str, profile: str) -> List[Dict[str, object]]:
    path = _history_dir_for(run_id, profile) / run_daily.ranked_jobs_json(profile).name
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def _load_user_state_map(profile: str) -> Dict[str, Dict[str, object]]:
    path = USER_STATE_DIR / f"{profile}.json"
    try:
        data = load_user_state(path)
    except Exception:
        return {}
    if isinstance(data, dict):
        if all(isinstance(v, dict) for v in data.values()):
            return {str(k): v for k, v in data.items()}
        jobs = data.get("jobs")
        if isinstance(jobs, list):
            mapping: Dict[str, Dict[str, object]] = {}
            for item in jobs:
                if isinstance(item, dict) and item.get("id"):
                    mapping[str(item["id"])] = item
            return mapping
    return {}


def _format_job_line(
    job: Dict[str, object],
    changed_fields: Dict[str, List[str]] | None,
    user_state: Dict[str, Dict[str, object]],
) -> str:
    title = job.get("title") or "Untitled"
    url = job.get("apply_url") or job.get("detail_url") or job_identity(job) or "—"
    ident = str(job.get("job_id") or job_identity(job))
    status_note = ""
    if ident in user_state:
        record = user_state.get(ident) or {}
        status = record.get("status") if isinstance(record, dict) else None
        status_norm = str(status or "").strip().upper()
        if status_norm in {"APPLIED", "IGNORE"}:
            status_note = f" (status: {status_norm}, priority=low)"
        elif status_norm:
            status_note = f" (status: {status_norm})"
    line = f"- {title} — {url}"
    if changed_fields:
        key = run_daily._job_key(job)
        diff = changed_fields.get(key)
        if diff:
            line += f" (changed: {', '.join(diff)})"
    if status_note:
        line += status_note
    return line


def _sorted_jobs(jobs: List[Dict[str, object]]) -> List[Dict[str, object]]:
    return sorted(
        jobs,
        key=lambda job: (
            -float(job.get("score") or 0),
            (job.get("apply_url") or job.get("detail_url") or "").lower(),
        ),
    )


def _report(
    profile: str,
    target_meta: Dict[str, object],
    prev_meta: Dict[str, object] | None,
    limit: int,
) -> None:
    run_id = target_meta["run_id"]
    prev_id = prev_meta["run_id"] if prev_meta else None
    print(f"Changes since last run for profile {profile}:")
    print(f"  current run: {run_id}")
    if prev_id:
        print(f"  previous run: {prev_id}")
    else:
        print("  previous run: none (first run)")

    curr_jobs = _load_ranked(run_id, profile)
    prev_jobs = _load_ranked(prev_id, profile) if prev_id else []
    new_jobs, changed_jobs, removed_jobs, changed_fields = run_daily._diff(prev_jobs, curr_jobs)

    counts = {"new": len(new_jobs), "changed": len(changed_jobs), "removed": len(removed_jobs)}
    print("Counts:", counts)

    user_state = _load_user_state_map(profile)

    def _print_section(label: str, jobs: List[Dict[str, object]], changed_fields_map=None) -> None:
        print(f"### {label} ({min(len(jobs), limit)} of {len(jobs)})")
        if not jobs:
            print("  (none)")
            return
        for job in _sorted_jobs(jobs)[:limit]:
            print("  " + _format_job_line(job, changed_fields_map, user_state))

    _print_section("New", new_jobs)
    _print_section("Changed", changed_jobs, changed_fields)
    _print_section("Removed", removed_jobs)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default="cs")
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--run_id", help="Target run_id (default: latest)")
    args = ap.parse_args()

    target_meta = _select_run(args.profile, args.run_id)
    prev_meta = _get_previous_run(args.profile, target_meta["run_id"])
    _report(args.profile, target_meta, prev_meta, args.limit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
