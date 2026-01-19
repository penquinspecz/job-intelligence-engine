#!/usr/bin/env python3
"""
Daily runner: pipeline -> score -> diff -> optional Discord alert.

State files live in data/state/.
Designed to run locally now and on AWS later (cron/EventBridge).

Examples:
  python scripts/run_daily.py --profile cs --us_only --no_post
  python scripts/run_daily.py --profiles cs,tam,se --us_only --min_alert_score 85 --no_post
  DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/..." python scripts/run_daily.py --profile cs --us_only
"""

from __future__ import annotations

import argparse
import atexit
import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys
import time
import runpy
import importlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple, Optional
import urllib.error
import urllib.request

from ji_engine.utils.dotenv import load_dotenv
from ji_engine.utils.job_identity import job_identity
from ji_engine.config import (
    DATA_DIR,
    STATE_DIR,
    HISTORY_DIR,
    RUN_METADATA_DIR,
    LOCK_PATH,
    ranked_jobs_json,
    ranked_jobs_csv,
    ranked_families_json,
    shortlist_md as shortlist_md_path,
    state_last_ranked,
    ensure_dirs,
    REPO_ROOT,
    SNAPSHOT_DIR,
    ENRICHED_JOBS_JSON,
    RAW_JOBS_JSON,
    LABELED_JOBS_JSON,
)
def _unavailable_summary() -> str:
    try:
        data = json.loads(ENRICHED_JOBS_JSON.read_text(encoding="utf-8"))
    except Exception:
        return ""
    reasons: Dict[str, int] = {}
    for j in data if isinstance(data, list) else []:
        if j.get("enrich_status") == "unavailable":
            r = j.get("enrich_reason") or "unavailable"
            reasons[r] = reasons.get(r, 0) + 1
    if not reasons:
        return ""
    return ", ".join(f"{k}={v}" for k, v in sorted(reasons.items()))

logger = logging.getLogger(__name__)
USE_SUBPROCESS = True
LAST_RUN_JSON = STATE_DIR / "last_run.json"


def _flush_logging() -> None:
    for handler in logging.getLogger().handlers:
        handler.flush()


def _warn_if_not_user_writable(paths: List[Path], *, context: str) -> None:
    """
    Best-effort warning: if a path exists but is not writable by the current user,
    log a helpful warning (common when artifacts were created as root in Docker).

    This is intentionally non-fatal and cross-platform.
    """
    non_writable: List[Path] = []
    for p in paths:
        try:
            if not p.exists():
                continue
            if not os.access(str(p), os.W_OK):
                non_writable.append(p)
        except Exception:
            # Never fail the run due to a permissions check.
            continue

    if not non_writable:
        return

    hint = (
        "Some artifacts exist but are not writable by your current user. "
        "This often happens if you previously ran the pipeline in Docker as root. "
        "Fix ownership/permissions and re-run."
    )
    if os.name == "posix":
        hint += " Example fix: `sudo chown -R $(id -u):$(id -g) data state`"

    logger.warning(
        "Non-writable pipeline artifacts detected (%s): %s. %s",
        context,
        ", ".join(str(p) for p in non_writable[:12]) + (" ..." if len(non_writable) > 12 else ""),
        hint,
    )


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:  # type: ignore[override]
        payload = {
            "time": datetime.utcnow().isoformat(),
            "level": record.levelname,
            "msg": record.getMessage(),
        }
        return json.dumps(payload, ensure_ascii=False)

load_dotenv()  # loads .env if present; won't override exported env vars
ensure_dirs()


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _pid_alive(pid: int) -> bool:
    """Return True if PID exists (best-effort)."""
    try:
        os.kill(pid, 0)  # does not kill; just checks
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but we don't have permission to signal it.
        return True


def _acquire_lock(timeout_sec: int = 0) -> None:
    """
    Prevent overlapping runs.
    Creates a lock file with the current PID. If it already exists:
      - if timeout_sec == 0: exit immediately
      - else: wait up to timeout_sec
    Also detects stale locks (PID no longer running).
    """
    start = time.time()
    pid = os.getpid()

    while True:
        try:
            # exclusive create
            fd = os.open(str(LOCK_PATH), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, "w") as f:
                f.write(str(pid))
            break
        except FileExistsError:
            # stale-lock detection
            try:
                existing_pid = int(LOCK_PATH.read_text(encoding="utf-8").strip() or "0")
            except Exception:
                existing_pid = 0

            if existing_pid and not _pid_alive(existing_pid):
                logger.warning(f"⚠️ Stale lock detected (pid={existing_pid}). Removing {LOCK_PATH}.")
                try:
                    LOCK_PATH.unlink(missing_ok=True)
                except Exception:
                    pass
                continue

            if timeout_sec == 0:
                raise SystemExit(f"Another run is already in progress (lock: {LOCK_PATH}).")
            if time.time() - start > timeout_sec:
                raise SystemExit(f"Timed out waiting for lock: {LOCK_PATH}.")
            time.sleep(2)

    def _cleanup() -> None:
        try:
            LOCK_PATH.unlink(missing_ok=True)
        except Exception:
            pass

    atexit.register(_cleanup)


def _run(cmd: List[str], *, stage: str) -> None:
    logger.info("\n$ " + " ".join(cmd))
    if USE_SUBPROCESS:
        result = subprocess.run(
            cmd,
            cwd=str(REPO_ROOT),
            text=True,
            capture_output=True,
        )

        stdout_tail = (result.stdout or "")[-4000:]
        stderr_tail = (result.stderr or "")[-4000:]

        if stdout_tail:
            logger.info(stdout_tail.rstrip())
        if stderr_tail:
            logger.info(stderr_tail.rstrip())
        _flush_logging()

        if result.returncode != 0:
            raise subprocess.CalledProcessError(
                result.returncode,
                cmd,
                output=stdout_tail,
                stderr=stderr_tail,
            )
        return

    # In-process fallback: attempt to run module/script directly
    argv = cmd[1:] if cmd and cmd[0] == sys.executable else cmd
    if argv and argv[0] == "-m":
        module_name = argv[1]
        args = argv[2:]
        old_argv = sys.argv
        sys.argv = [module_name, *args]
        try:
            mod = importlib.import_module(module_name)
            if hasattr(mod, "main"):
                rc = mod.main()
                if rc not in (None, 0):
                    raise SystemExit(rc)
            else:
                raise SystemExit(f"Module {module_name} has no main()")
        except SystemExit as e:
            if _normalize_exit_code(e.code) != 0:
                raise
        finally:
            sys.argv = old_argv
        _flush_logging()
    else:
        script_path = argv[0]
        args = argv[1:]
        old_argv = sys.argv
        sys.argv = [script_path, *args]
        try:
            runpy.run_path(script_path, run_name="__main__")
        except SystemExit as e:
            if _normalize_exit_code(e.code) != 0:
                raise
        finally:
            sys.argv = old_argv
        _flush_logging()


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def _run_metadata_path(run_id: str) -> Path:
    safe_id = _sanitize_run_id(run_id)
    return RUN_METADATA_DIR / f"{safe_id}.json"


def _sanitize_run_id(run_id: str) -> str:
    return run_id.replace(":", "").replace("-", "").replace(".", "")


def _history_run_dir(run_id: str, profile: str) -> Path:
    run_date = run_id.split("T")[0]
    sanitized = _sanitize_run_id(run_id)
    return HISTORY_DIR / run_date / sanitized / profile


def _latest_profile_dir(profile: str) -> Path:
    return HISTORY_DIR / "latest" / profile


def _copy_artifact(src: Path, dest: Path) -> None:
    if not src.exists():
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)


def _archive_profile_artifacts(
    run_id: str,
    profile: str,
    run_metadata_path: Path,
    summary_payload: Dict[str, object],
) -> None:
    history_dir = _history_run_dir(run_id, profile)
    latest_dir = _latest_profile_dir(profile)
    artifacts = [
        ranked_jobs_json(profile),
        ranked_jobs_csv(profile),
        ranked_families_json(profile),
        shortlist_md_path(profile),
    ]
    for src in artifacts:
        dest_history = history_dir / src.name
        dest_latest = latest_dir / src.name
        _copy_artifact(src, dest_history)
        _copy_artifact(src, dest_latest)
    _copy_artifact(run_metadata_path, latest_dir / "run_metadata.json")
    summary_file = "run_summary.txt"
    for dest in (history_dir, latest_dir):
        dest_summary = dest / summary_file
        dest_summary.parent.mkdir(parents=True, exist_ok=True)
        dest_summary.write_text(json.dumps(summary_payload, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    # keep run_metadata per run for history and single copy for latest
    _copy_artifact(run_metadata_path, history_dir / run_metadata_path.name)
    _copy_artifact(run_metadata_path, latest_dir / "run_metadata.json")

def _persist_run_metadata(
    run_id: str,
    telemetry: Dict[str, Any],
    profiles: List[str],
    flags: Dict[str, Any],
    diff_counts: Dict[str, Dict[str, int]],
    scoring_inputs_by_profile: Dict[str, Dict[str, Optional[str]]],
    scoring_input_selection_by_profile: Dict[str, Dict[str, Any]],
) -> Path:
    run_report_schema_version = "1"
    inputs: Dict[str, Dict[str, Optional[str]]] = {
        "raw_jobs_json": _file_metadata(RAW_JOBS_JSON),
        "labeled_jobs_json": _file_metadata(LABELED_JOBS_JSON),
        "enriched_jobs_json": _file_metadata(ENRICHED_JOBS_JSON),
    }
    ai_path = ENRICHED_JOBS_JSON.with_name("openai_enriched_jobs_ai.json")
    if ai_path.exists():
        inputs["ai_enriched_jobs_json"] = _file_metadata(ai_path)

    outputs_by_profile: Dict[str, Dict[str, Dict[str, Optional[str]]]] = {}
    for profile in profiles:
        outputs_by_profile[profile] = {
            "ranked_json": _output_metadata(ranked_jobs_json(profile)),
            "ranked_csv": _output_metadata(ranked_jobs_csv(profile)),
            "ranked_families_json": _output_metadata(ranked_families_json(profile)),
            "shortlist_md": _output_metadata(shortlist_md_path(profile)),
        }

    payload = {
        "run_report_schema_version": run_report_schema_version,
        "run_id": run_id,
        "status": telemetry.get("status"),
        "profiles": profiles,
        "flags": flags,
        "timestamps": {
            "started_at": telemetry.get("started_at"),
            "ended_at": telemetry.get("ended_at"),
        },
        "stage_durations": telemetry.get("stages", {}),
        "diff_counts": diff_counts,
        "inputs": inputs,
        "scoring_inputs_by_profile": scoring_inputs_by_profile,
        "scoring_input_selection_by_profile": scoring_input_selection_by_profile,
        "outputs_by_profile": outputs_by_profile,
        "git_sha": _best_effort_git_sha(),
        "image_tag": os.environ.get("IMAGE_TAG"),
    }
    payload["success"] = telemetry.get("success", False)
    if telemetry.get("failed_stage"):
        payload["failed_stage"] = telemetry["failed_stage"]
    path = _run_metadata_path(run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return path


def _hash_file(path: Path) -> Optional[str]:
    if not path.exists():
        return None
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except Exception:
        return None


def _file_metadata(path: Path) -> Dict[str, Optional[str]]:
    return {
        "path": str(path),
        "mtime_iso": _file_mtime_iso(path),
        "sha256": _hash_file(path),
    }


def _candidate_metadata(path: Path) -> Dict[str, Optional[str]]:
    meta = _file_metadata(path)
    meta["exists"] = path.exists()
    return meta


def _output_metadata(path: Path) -> Dict[str, Optional[str]]:
    return {
        "path": str(path),
        "sha256": _hash_file(path),
    }


def _best_effort_git_sha() -> Optional[str]:
    env_sha = os.environ.get("GIT_SHA")
    if env_sha:
        return env_sha
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(REPO_ROOT),
            text=True,
            capture_output=True,
        )
        if result.returncode == 0:
            return (result.stdout or "").strip() or None
    except Exception:
        return None
    return None


def _normalize_exit_code(code: Any) -> int:
    if code is None:
        return 0
    if isinstance(code, int):
        return code
    if isinstance(code, str):
        try:
            return int(code)
        except ValueError:
            pass
    return 1


def _resolve_score_input_path(args: argparse.Namespace) -> Tuple[Optional[Path], Optional[str]]:
    """
    Decide which input file to feed into score_jobs based on CLI flags.
    Returns (path, error_message). If error_message is not None, caller should abort.
    """
    ai_path = ENRICHED_JOBS_JSON.with_name("openai_enriched_jobs_ai.json")

    if args.ai_only:
        if not ai_path.exists():
            return None, (
                f"AI-only mode requires AI-enriched input at {ai_path}. "
                "Ensure --ai is set and run_ai_augment has produced this file."
            )
        return ai_path, None

    if args.no_enrich:
        # Prefer enriched if it already exists and is newer than labeled; otherwise fall back to labeled.
        enriched_exists = ENRICHED_JOBS_JSON.exists()
        labeled_exists = LABELED_JOBS_JSON.exists()

        if enriched_exists and labeled_exists:
            m_enriched = ENRICHED_JOBS_JSON.stat().st_mtime
            m_labeled = LABELED_JOBS_JSON.stat().st_mtime
            if m_enriched > m_labeled:
                return ENRICHED_JOBS_JSON, None
            logger.warning(
                "Enriched input is older than labeled; using labeled for scoring. "
                "enriched_mtime=%s labeled_mtime=%s",
                m_enriched,
                m_labeled,
            )
            return LABELED_JOBS_JSON, None

        if enriched_exists:
            return ENRICHED_JOBS_JSON, None
        if labeled_exists:
            return LABELED_JOBS_JSON, None
        return None, (
            f"Scoring input not found: {ENRICHED_JOBS_JSON} or {LABELED_JOBS_JSON}. "
            "Run without --no_enrich to generate enrichment, or ensure labeled data exists."
        )

    # Default: expect enriched output
    if ENRICHED_JOBS_JSON.exists():
        return ENRICHED_JOBS_JSON, None

    return None, (
        f"Scoring input not found: {ENRICHED_JOBS_JSON}. "
        "Re-run without --no_enrich to produce enrichment output."
    )


def _score_input_selection_detail(args: argparse.Namespace) -> Dict[str, Any]:
    ai_path = ENRICHED_JOBS_JSON.with_name("openai_enriched_jobs_ai.json")
    enriched_meta = _candidate_metadata(ENRICHED_JOBS_JSON)
    labeled_meta = _candidate_metadata(LABELED_JOBS_JSON)
    ai_meta = _candidate_metadata(ai_path)
    candidates = [ai_meta, enriched_meta, labeled_meta]
    flags = {"no_enrich": bool(args.no_enrich), "ai": bool(args.ai), "ai_only": bool(args.ai_only)}

    decision: Dict[str, Any] = {"flags": flags, "comparisons": {}}
    selected_path: Optional[Path] = None
    reason = ""

    def _ai_note() -> str:
        if args.ai and not args.ai_only:
            return " (ai does not change selection; prefer_ai affects scoring only)"
        return ""

    if args.ai_only:
        decision["rule"] = "ai_only"
        reason = "ai_only requires AI-enriched input"
        selected_path = ai_path if ai_path.exists() else None
        decision["reason"] = reason
        return {
            "selected": _file_metadata(selected_path) if selected_path else None,
            "candidates": candidates,
            "decision": decision,
        }

    if args.no_enrich:
        decision["rule"] = "no_enrich_compare"
        comparisons: Dict[str, Any] = {}
        if ENRICHED_JOBS_JSON.exists() and LABELED_JOBS_JSON.exists():
            enriched_mtime = _file_mtime(ENRICHED_JOBS_JSON)
            labeled_mtime = _file_mtime(LABELED_JOBS_JSON)
            comparisons["enriched_mtime"] = enriched_mtime
            comparisons["labeled_mtime"] = labeled_mtime
            if (enriched_mtime or 0) > (labeled_mtime or 0):
                selected_path = ENRICHED_JOBS_JSON
                reason = "enriched newer than labeled"
                comparisons["winner"] = "enriched"
            else:
                selected_path = LABELED_JOBS_JSON
                reason = "labeled newer or same mtime as enriched"
                comparisons["winner"] = "labeled"
        elif ENRICHED_JOBS_JSON.exists():
            selected_path = ENRICHED_JOBS_JSON
            reason = "enriched exists and labeled missing"
            comparisons["winner"] = "enriched"
        elif LABELED_JOBS_JSON.exists():
            selected_path = LABELED_JOBS_JSON
            reason = "labeled exists and enriched missing"
            comparisons["winner"] = "labeled"
        else:
            reason = "no_enrich requires labeled or enriched input"
        decision["comparisons"] = comparisons
        decision["reason"] = reason + _ai_note()
        return {
            "selected": _file_metadata(selected_path) if selected_path else None,
            "candidates": candidates,
            "decision": decision,
        }

    decision["rule"] = "default_enriched_required"
    if ENRICHED_JOBS_JSON.exists():
        selected_path = ENRICHED_JOBS_JSON
        reason = "default requires enriched input"
    else:
        reason = "enriched input missing"
    decision["reason"] = reason + _ai_note()
    return {
        "selected": _file_metadata(selected_path) if selected_path else None,
        "candidates": candidates,
        "decision": decision,
    }


def _safe_len(path: Path) -> int:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return len(data)
    except Exception:
        return 0
    return 0


def _load_last_run() -> Dict[str, Any]:
    if not LAST_RUN_JSON.exists():
        return {}
    try:
        return json.loads(LAST_RUN_JSON.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_last_run(payload: Dict[str, Any]) -> None:
    _write_json(LAST_RUN_JSON, payload)


def validate_config(args: argparse.Namespace, webhook: str) -> None:
    """
    Ensure required env/config combos for CLI args before running.
    """
    if args.test_post and not webhook:
        logger.error("test_post requires DISCORD_WEBHOOK_URL; set it or unset --test_post")
        raise SystemExit(2)
    if args.ai_only and not args.ai:
        logger.error("--ai_only depends on --ai")
        raise SystemExit(2)
    if args.scrape_only and args.ai_only:
        logger.error("--scrape_only and --ai_only are mutually exclusive")
        raise SystemExit(2)


def _file_mtime(path: Path) -> Optional[float]:
    try:
        return path.stat().st_mtime
    except Exception:
        return None


def _file_mtime_iso(path: Path) -> Optional[str]:
    ts = _file_mtime(path)
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, timezone.utc).isoformat()


def _setup_logging(json_mode: bool) -> None:
    if not logging.getLogger().hasHandlers() or json_mode:
        handlers = []
        if json_mode:
            h = logging.StreamHandler()
            h.setFormatter(JsonFormatter())
            handlers.append(h)
            logging.basicConfig(level=logging.INFO, handlers=handlers, force=True)
        else:
            logging.basicConfig(
                level=logging.INFO,
                format="%(asctime)s %(levelname)s %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )


def _should_short_circuit(prev_hashes: Dict[str, Any], curr_hashes: Dict[str, Any]) -> bool:
    return all(
        curr_hashes.get(k) is not None and curr_hashes.get(k) == prev_hashes.get(k)
        for k in ("raw", "labeled", "enriched")
    )


def _job_key(job: Dict[str, Any]) -> str:
    return str(job.get("job_id") or job_identity(job))


def _job_description_text(job: Dict[str, Any]) -> str:
    return (
        job.get("description_text")
        or job.get("jd_text")
        or job.get("description")
        or job.get("descriptionHtml")
        or ""
    )


def _job_field_value(job: Dict[str, Any], field: str) -> Any:
    if field == "location":
        return job.get("location") or job.get("locationName") or ""
    if field == "description_text":
        return _job_description_text(job)
    return job.get(field)


_FIELD_DIFF_KEYS: List[Tuple[str, str]] = [
    ("title", "title"),
    ("location", "location"),
    ("team", "team"),
    ("score", "score"),
    ("description_text", "description"),
]


def _hash_job(job: Dict[str, Any]) -> str:
    desc_hash = hashlib.sha256(_job_description_text(job).encode("utf-8")).hexdigest()
    payload = {
        "title": job.get("title"),
        "location": job.get("location") or job.get("locationName"),
        "team": job.get("team"),
        "description_text_hash": desc_hash,
    }
    raw = json.dumps(payload, sort_keys=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _diff(
    prev: List[Dict[str, Any]],
    curr: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, List[str]]]:
    prev_map = {_job_key(j): (j, _hash_job(j)) for j in prev}
    curr_map = {_job_key(j): (j, _hash_job(j)) for j in curr}

    new_jobs: List[Dict[str, Any]] = []
    changed_jobs: List[Dict[str, Any]] = []
    removed_jobs: List[Dict[str, Any]] = []
    changed_fields: Dict[str, List[str]] = {}

    for k, (cj, ch) in curr_map.items():
        if k not in prev_map:
            new_jobs.append(cj)
        else:
            pj, ph = prev_map[k]
            if ph != ch:
                changes: List[str] = []

                for key, label in _FIELD_DIFF_KEYS:
                    if _job_field_value(pj, key) != _job_field_value(cj, key):
                        changes.append(label)

                changed_fields[k] = changes
                changed_jobs.append(cj)

    for k, (pj, _) in prev_map.items():
        if k not in curr_map:
            removed_jobs.append(pj)

    new_jobs.sort(key=lambda x: x.get("score", 0), reverse=True)
    changed_jobs.sort(key=lambda x: x.get("score", 0), reverse=True)
    removed_jobs.sort(key=lambda x: (x.get("apply_url") or "", x.get("title") or ""))
    return new_jobs, changed_jobs, removed_jobs, changed_fields


def _format_before_after(
    job: Dict[str, Any],
    prev_job: Optional[Dict[str, Any]],
    diff_labels: List[str],
) -> str:
    """Format before/after values for changed fields (excluding description content)."""
    parts: List[str] = []
    for field in ("title", "location", "team", "score"):
        if field in diff_labels:
            before = _job_field_value(prev_job, field) if prev_job else "?"
            after = _job_field_value(job, field)
            parts.append(f"{field}: {before} → {after}")
    # Description changes: just note it changed, don't dump content
    if "description" in diff_labels:
        parts.append("description_text")
    return ", ".join(parts) if parts else "details"


def _sort_key_score_url(job: Dict[str, Any]) -> Tuple[float, str]:
    """Sort key: score desc, url asc for deterministic ordering."""
    return (-job.get("score", 0), (job.get("apply_url") or "").lower())


def _sort_key_url(job: Dict[str, Any]) -> str:
    """Sort key: url asc for removed items."""
    return (job.get("apply_url") or "").lower()


def format_changes_section(
    new_jobs: List[Dict[str, Any]],
    changed_jobs: List[Dict[str, Any]],
    removed_jobs: List[Dict[str, Any]],
    changed_fields: Dict[str, List[str]],
    prev_map: Dict[str, Dict[str, Any]],
    prev_exists: bool,
    min_alert_score: int,
    limit: int = 10,
) -> str:
    """
    Pure helper: returns markdown for "Changes since last run" section.
    
    Filtering rules:
    - Include items where job.score >= min_alert_score OR the item is removed.
    - For changed items, show before/after for title, location, team, score.
    - For description changes, just note "description_text" (no content dump).
    
    Sorting rules (deterministic):
    - New/Changed: score desc, url asc
    - Removed: url asc
    """
    lines: List[str] = ["", "## Changes since last run"]
    
    if not prev_exists:
        lines.append("No previous run to diff against.")
        return "\n".join(lines)
    
    # Filter by min_alert_score (new/changed only; removed always included)
    filtered_new = [j for j in new_jobs if j.get("score", 0) >= min_alert_score]
    filtered_changed = [j for j in changed_jobs if j.get("score", 0) >= min_alert_score]
    filtered_removed = removed_jobs  # Always include all removed
    
    # Sort deterministically
    filtered_new_sorted = sorted(filtered_new, key=_sort_key_score_url)[:limit]
    filtered_changed_sorted = sorted(filtered_changed, key=_sort_key_score_url)[:limit]
    filtered_removed_sorted = sorted(filtered_removed, key=_sort_key_url)[:limit]
    
    # New section
    lines.append(f"### New ({len(filtered_new)}) list items")
    if not filtered_new_sorted:
        lines.append("_None_")
    else:
        for job in filtered_new_sorted:
            title = job.get("title") or "Untitled"
            url = job.get("apply_url") or job.get("detail_url") or job_identity(job) or "—"
            lines.append(f"- {title} — {url}")
    
    lines.append("")
    
    # Changed section
    lines.append(f"### Changed ({len(filtered_changed)}) list items")
    if not filtered_changed_sorted:
        lines.append("_None_")
    else:
        for job in filtered_changed_sorted:
            title = job.get("title") or "Untitled"
            url = job.get("apply_url") or job.get("detail_url") or job_identity(job) or "—"
            key = _job_key(job)
            diff_labels = changed_fields.get(key, [])
            prev_job = prev_map.get(key)
            change_desc = _format_before_after(job, prev_job, diff_labels)
            lines.append(f"- {title} — {url} (changed: {change_desc})")
    
    lines.append("")
    
    # Removed section (always include all, no score filtering)
    lines.append(f"### Removed ({len(removed_jobs)}) list items")
    if not filtered_removed_sorted:
        lines.append("_None_")
    else:
        for job in filtered_removed_sorted:
            title = job.get("title") or "Untitled"
            url = job.get("apply_url") or job.get("detail_url") or job_identity(job) or "—"
            lines.append(f"- {title} — {url}")
    
    return "\n".join(lines)


def _append_shortlist_changes_section(
    shortlist_path: Path,
    profile: str,
    new_jobs: List[Dict[str, Any]],
    changed_jobs: List[Dict[str, Any]],
    removed_jobs: List[Dict[str, Any]],
    prev_exists: bool,
    changed_fields: Dict[str, List[str]],
    prev_jobs: Optional[List[Dict[str, Any]]] = None,
    min_alert_score: int = 0,
) -> None:
    """Append 'Changes since last run' section to shortlist markdown."""
    if not shortlist_path.exists():
        return

    # Build prev_map for looking up before values
    prev_map: Dict[str, Dict[str, Any]] = {}
    if prev_jobs:
        prev_map = {_job_key(j): j for j in prev_jobs}

    section_md = format_changes_section(
        new_jobs=new_jobs,
        changed_jobs=changed_jobs,
        removed_jobs=removed_jobs,
        changed_fields=changed_fields,
        prev_map=prev_map,
        prev_exists=prev_exists,
        min_alert_score=min_alert_score,
    )

    content = shortlist_path.read_text(encoding="utf-8")
    if not content.endswith("\n"):
        content += "\n"
    content += section_md + "\n"
    shortlist_path.write_text(content, encoding="utf-8")


def _dispatch_alerts(
    profile: str,
    webhook: str,
    new_jobs: List[Dict[str, Any]],
    changed_jobs: List[Dict[str, Any]],
    removed_jobs: List[Dict[str, Any]],
    interesting_new: List[Dict[str, Any]],
    interesting_changed: List[Dict[str, Any]],
    lines: List[str],
    args: argparse.Namespace,
    unavailable_summary: str,
) -> None:
    total_changes = len(new_jobs) + len(changed_jobs) + len(removed_jobs)
    if total_changes == 0:
        logger.info(
            "No meaningful changes detected (new=%d, changed=%d, removed=%d); skipping Discord alerts.",
            len(new_jobs),
            len(changed_jobs),
            len(removed_jobs),
        )
        return

    if not webhook:
        logger.info(
            f"ℹ️ No alerts ({profile}) (new={len(new_jobs)}, changed={len(changed_jobs)}; webhook=unset)."
        )
        return

    if not (interesting_new or interesting_changed):
        logger.info(
            f"ℹ️ No alerts ({profile}) (new={len(new_jobs)}, changed={len(changed_jobs)}; webhook=set)."
        )
        return

    msg_lines = list(lines)
    if args.no_post:
        msg = "\n".join(msg_lines)
        logger.info(f"Skipping Discord post (--no_post). Message for {profile} would have been:\n")
        logger.info(msg)
        return

    if unavailable_summary:
        msg_lines.append(f"Unavailable reasons: {unavailable_summary}")

    msg = "\n".join(msg_lines)
    ok = _post_discord(webhook, msg)
    logger.info(
        f"✅ Discord alert sent ({profile})." if ok else "⚠️ Discord alert NOT sent (pipeline still completed)."
    )


def _post_discord(webhook_url: str, message: str) -> bool:
    """
    Returns True if posted successfully, False otherwise.
    Never raises (so your pipeline still completes).
    """
    if not webhook_url or "discord.com/api/webhooks/" not in webhook_url:
        logger.warning("⚠️ DISCORD_WEBHOOK_URL missing or doesn't look like a Discord webhook URL. Skipping post.")
        return False

    payload = {"content": message}
    data = json.dumps(payload).encode("utf-8")

    req = urllib.request.Request(
        webhook_url,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X) job-intelligence-engine/1.0",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            resp.read()
        return True
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        logger.error(f"Discord webhook POST failed: {e.code}")
        logger.error(body[:2000])
        if e.code == 404 and "10015" in body:
            logger.warning("⚠️ Discord says: Unknown Webhook (rotated/deleted/wrong URL). Update DISCORD_WEBHOOK_URL in .env.")
        return False
    except Exception as e:
        logger.error(f"Discord webhook POST failed: {e!r}")
        return False


def _post_failure(webhook_url: str, stage: str, error: str, no_post: bool, *, stdout: str = "", stderr: str = "") -> None:
    """Best-effort failure notification. Never raises."""
    if no_post or not webhook_url:
        return

    stdout_tail = (stdout or "")[-1800:]
    stderr_tail = (stderr or "")[-1800:]

    msg = (
        "**🚨 Job Pipeline FAILED**\n"
        f"Stage: `{stage}`\n"
        f"Time: `{_utcnow_iso()}`\n"
        f"Error:\n```{error[-1800:]}```"
        f"\n\n**stderr (tail)**:\n```{stderr_tail}```"
        f"\n\n**stdout (tail)**:\n```{stdout_tail}```"
    )
    _post_discord(webhook_url, msg)


def _resolve_profiles(args: argparse.Namespace) -> List[str]:
    """Resolve --profiles (comma-separated) else fallback to --profile."""
    profiles_arg = (args.profiles or "").strip()
    if profiles_arg:
        profiles = [p.strip() for p in profiles_arg.split(",") if p.strip()]
    else:
        profiles = [args.profile.strip()]

    # de-dupe while preserving order
    seen = set()
    out: List[str] = []
    for p in profiles:
        if p not in seen:
            seen.add(p)
            out.append(p)

    if not out:
        raise SystemExit("No profiles provided.")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()

    ap.add_argument("--profile", default="cs", help="Scoring profile name (cs|tam|se)")
    ap.add_argument(
        "--profiles",
        default="",
        help="Comma-separated profiles to run (e.g. cs or cs,tam,se). If set, overrides --profile.",
    )
    ap.add_argument("--us_only", action="store_true")
    ap.add_argument("--min_alert_score", type=int, default=85)
    ap.add_argument("--no_post", action="store_true", help="Run pipeline but do not send Discord webhook")
    ap.add_argument("--test_post", action="store_true", help="Send a test message to Discord and exit")
    ap.add_argument("--no_enrich", action="store_true", help="Skip enrichment step (CI / offline safe)")
    ap.add_argument("--ai", action="store_true", help="Run AI augment stage after enrichment")
    ap.add_argument("--ai_only", action="store_true", help="Run enrich + AI augment only (no scoring/alerts)")
    ap.add_argument("--scrape_only", action="store_true", help="Run scrape stage only (no classify/enrich/score)")
    ap.add_argument(
        "--no_subprocess",
        action="store_true",
        help="Run stages in-process (library mode). Default uses subprocesses.",
    )
    ap.add_argument("--log_json", action="store_true", help="Emit JSON logs for aggregation systems")
    ap.add_argument("--print_paths", action="store_true", help="Print resolved data/state/history paths")

    args = ap.parse_args()
    run_id = _utcnow_iso()
    global USE_SUBPROCESS
    USE_SUBPROCESS = not args.no_subprocess
    _setup_logging(args.log_json)
    webhook = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()

    validate_config(args, webhook)

    if args.print_paths:
        print("DATA_DIR=", DATA_DIR)
        print("STATE_DIR=", STATE_DIR)
        print("HISTORY_DIR=", HISTORY_DIR)
        print("RUN_METADATA_DIR=", RUN_METADATA_DIR)
        return 0

    if args.test_post:
        if not webhook:
            raise SystemExit("DISCORD_WEBHOOK_URL not set (check .env and export).")
        ok = _post_discord(webhook, "test_post ✅ (run_daily)")
        logger.info("✅ test_post sent" if ok else "⚠️ test_post failed")
        return 0

    _acquire_lock(timeout_sec=0)
    logger.info(f"===== jobintel start {_utcnow_iso()} pid={os.getpid()} =====")

    telemetry: Dict[str, Any] = {
        "run_id": run_id,
        "started_at": _utcnow_iso(),
        "status": "started",
        "stages": {},
        "ai_requested": bool(args.ai),
        "ai_ran": False,
    }
    prev_run = _load_last_run()
    prev_hashes = prev_run.get("hashes", {}) if prev_run else {}
    prev_ai = prev_run.get("ai", {}) if prev_run else {}
    curr_hashes = {
        "raw": _hash_file(RAW_JOBS_JSON),
        "labeled": _hash_file(LABELED_JOBS_JSON),
        "enriched": _hash_file(ENRICHED_JOBS_JSON),
    }
    ai_path = ENRICHED_JOBS_JSON.with_name("openai_enriched_jobs_ai.json")
    ai_hash = _hash_file(ai_path)
    ai_mtime = _file_mtime(ai_path)

    profiles_list: List[str] = []
    diff_counts_by_profile: Dict[str, Dict[str, int]] = {}
    scoring_inputs_by_profile: Dict[str, Dict[str, Optional[str]]] = {}
    scoring_input_selection_by_profile: Dict[str, Dict[str, Any]] = {}
    flag_payload = {
        "profile": args.profile,
        "profiles": args.profiles,
        "us_only": args.us_only,
        "no_enrich": args.no_enrich,
        "ai": args.ai,
        "ai_only": args.ai_only,
    }

    def _finalize(status: str, extra: Optional[Dict[str, Any]] = None) -> None:
        telemetry["status"] = status
        telemetry["hashes"] = {
            "raw": _hash_file(RAW_JOBS_JSON),
            "labeled": _hash_file(LABELED_JOBS_JSON),
            "enriched": _hash_file(ENRICHED_JOBS_JSON),
        }
        telemetry["counts"] = {
            "raw": _safe_len(RAW_JOBS_JSON),
            "labeled": _safe_len(LABELED_JOBS_JSON),
            "enriched": _safe_len(ENRICHED_JOBS_JSON),
        }
        # First-class AI telemetry (even on short-circuit runs).
        telemetry["ai_requested"] = bool(telemetry.get("ai_requested", False))
        telemetry["ai_ran"] = bool(telemetry.get("ai_ran", False))
        telemetry["ai_output_hash"] = _hash_file(ai_path)
        telemetry["ai_output_mtime"] = _file_mtime_iso(ai_path)
        # Back-compat nested structure (keep for existing readers).
        telemetry["ai"] = {
            "ran": telemetry["ai_ran"],
            "output_hash": telemetry["ai_output_hash"],
            "output_mtime": telemetry["ai_output_mtime"],
        }
        telemetry["ended_at"] = _utcnow_iso()
        telemetry["success"] = status == "success"
        if extra:
            telemetry.update(extra)
        _write_last_run(telemetry)
        run_metadata_path = _persist_run_metadata(
            run_id,
            telemetry,
            profiles_list,
            flag_payload,
            diff_counts_by_profile,
            scoring_inputs_by_profile,
            scoring_input_selection_by_profile,
        )
        for profile in profiles_list:
            diffs = diff_counts_by_profile.get(profile, {"new": 0, "changed": 0, "removed": 0})
            summary_payload = {
                "run_id": run_id,
                "timestamp": telemetry["ended_at"],
                "profile": profile,
                "flags": flag_payload,
                "short_circuit": telemetry["status"] == "short_circuit",
                "diff_counts": diffs,
            }
            _archive_profile_artifacts(
                run_id,
                profile,
                run_metadata_path,
                summary_payload,
            )

    current_stage = "startup"

    def record_stage(name: str, fn) -> Any:
        t0 = time.time()
        try:
            result = fn()
        except SystemExit as e:
            code = _normalize_exit_code(e.code)
            if code == 0:
                result = None  # treat as success and continue
            else:
                raise
        telemetry["stages"][name] = {"duration_sec": round(time.time() - t0, 3)}
        return result

    try:
        profiles = _resolve_profiles(args)
        profiles_list[:] = profiles
        us_only_flag = ["--us_only"] if args.us_only else []
        ai_required = args.ai

        # Self-check: warn if common artifacts/directories are not writable (e.g., root-owned from Docker).
        _warn_if_not_user_writable(
            [
                DATA_DIR,
                STATE_DIR,
                RAW_JOBS_JSON,
                LABELED_JOBS_JSON,
                ENRICHED_JOBS_JSON,
                ENRICHED_JOBS_JSON.with_name("openai_enriched_jobs_ai.json"),
                LAST_RUN_JSON,
            ],
            context="startup",
        )

        # Snapshot presence check (fail fast with alert if missing and needed)
        snapshot_path = SNAPSHOT_DIR / "index.html"
        if not snapshot_path.exists():
            msg = (
                f"Snapshot not found at {snapshot_path}. "
                "Save https://openai.com/careers/search/ to data/openai_snapshots/index.html or switch mode."
            )
            raise RuntimeError(msg)

        # Short-circuit check (ai-aware)
        base_short = _should_short_circuit(prev_hashes, curr_hashes)

        def _ranked_up_to_date() -> bool:
            if ai_mtime is None:
                return False
            for p in profiles:
                rjson = ranked_jobs_json(p)
                if (not rjson.exists()) or ((_file_mtime(rjson) or 0) < ai_mtime):
                    return False
            return True

        def _update_ai_telemetry(ran: bool) -> None:
            telemetry.update(
                {
                    "ai_requested": True if ai_required else False,
                    "ai_ran": ran,
                    "ai_output_hash": _hash_file(ai_path),
                    "ai_output_mtime": _file_mtime_iso(ai_path),
                }
            )
            telemetry["ai"] = {
                "requested": telemetry["ai_requested"],
                "ran": telemetry["ai_ran"],
                "output_hash": telemetry["ai_output_hash"],
                "output_mtime": telemetry["ai_output_mtime"],
            }

        if base_short:
            # No-AI short-circuit: safe to skip everything downstream IF ranked artifacts exist.
            if not ai_required:
                missing_artifacts: List[Path] = []
                for p in profiles:
                    if not ranked_jobs_json(p).exists():
                        missing_artifacts.append(ranked_jobs_json(p))
                    if not ranked_jobs_csv(p).exists():
                        missing_artifacts.append(ranked_jobs_csv(p))
                    if not ranked_families_json(p).exists():
                        missing_artifacts.append(ranked_families_json(p))
                    if not shortlist_md_path(p).exists():
                        missing_artifacts.append(shortlist_md_path(p))

                if not missing_artifacts:
                    telemetry["hashes"] = curr_hashes
                    telemetry["counts"] = {
                        "raw": _safe_len(RAW_JOBS_JSON),
                        "labeled": _safe_len(LABELED_JOBS_JSON),
                        "enriched": _safe_len(ENRICHED_JOBS_JSON),
                    }
                    telemetry["stages"] = {"short_circuit": {"duration_sec": 0.0}}
                    _update_ai_telemetry(False)
                    _finalize("short_circuit")
                    logger.info(
                        "No changes detected (raw/labeled/enriched) and ranked artifacts present. "
                        "Short-circuiting downstream stages (scoring not required)."
                    )
                    return 0
                else:
                    logger.info(
                        "Short-circuit skipped because ranked artifacts are missing; will re-run scoring. Missing: %s",
                        ", ".join(str(p) for p in missing_artifacts),
                    )

            # AI-aware short-circuit: allow skipping scrape/classify/enrich, but only skip AI+scoring when fresh.
            prev_ai_hash = prev_run.get("ai_output_hash") or prev_ai.get("output_hash")
            prev_ai_mtime = prev_run.get("ai_output_mtime") or prev_ai.get("output_mtime")
            prev_ai_ran = bool(prev_run.get("ai_ran") or prev_ai.get("ran"))

            curr_ai_mtime_iso = _file_mtime_iso(ai_path)
            ai_fresh = bool(ai_path.exists()) and (
                (ai_hash is not None and ai_hash == prev_ai_hash) or (curr_ai_mtime_iso is not None and curr_ai_mtime_iso == prev_ai_mtime)
            )

            if ai_fresh and prev_ai_ran and _ranked_up_to_date():
                telemetry["hashes"] = curr_hashes
                telemetry["counts"] = {
                    "raw": _safe_len(RAW_JOBS_JSON),
                    "labeled": _safe_len(LABELED_JOBS_JSON),
                    "enriched": _safe_len(ENRICHED_JOBS_JSON),
                }
                telemetry["stages"] = {"short_circuit": {"duration_sec": 0.0}}
                _update_ai_telemetry(False)
                _finalize("short_circuit")
                logger.info("No changes detected and AI+ranked outputs fresh. Short-circuiting downstream stages.")
                return 0

            # We still want AI and/or scoring to run, but we can skip scrape/classify/enrich.
            if (not ai_path.exists()) or (not prev_ai_ran) or (not ai_fresh):
                current_stage = "ai_augment"
                telemetry["ai_ran"] = True
                record_stage(
                    current_stage,
                    lambda: _run([sys.executable, str(REPO_ROOT / "scripts" / "run_ai_augment.py")], stage=current_stage),
                )
                ai_mtime = _file_mtime(ai_path)
                ai_hash = _hash_file(ai_path)

            # Ensure scoring runs if ranked outputs missing or stale vs AI file
            for profile in profiles:
                ranked_json = ranked_jobs_json(profile)
                ranked_csv = ranked_jobs_csv(profile)
                ranked_families = ranked_families_json(profile)
                shortlist_md = shortlist_md_path(profile)

                scoring_input_selection_by_profile[profile] = _score_input_selection_detail(args)
                score_in, score_err = _resolve_score_input_path(args)
                scoring_inputs_by_profile[profile] = _file_metadata(score_in) if score_in else {
                    "path": None,
                    "mtime_iso": None,
                    "sha256": None,
                }

                need_score = (not ranked_json.exists())
                if ai_mtime is not None:
                    need_score = need_score or ((_file_mtime(ranked_json) or 0) < ai_mtime)
                else:
                    need_score = True

                if need_score:
                    current_stage = f"score:{profile}"
                    if score_err or score_in is None:
                        logger.error(score_err or "Unknown scoring input error")
                        _finalize("error", {"error": score_err or "score input missing", "failed_stage": current_stage})
                        return 2

                cmd = [
                        sys.executable,
                        str(REPO_ROOT / "scripts" / "score_jobs.py"),
                        "--profile",
                        profile,
                        "--in_path",
                        str(score_in),
                        "--out_json",
                        str(ranked_json),
                        "--out_csv",
                        str(ranked_csv),
                        "--out_families",
                        str(ranked_families),
                        "--out_md",
                        str(shortlist_md),
                    ] + us_only_flag
                if args.ai or args.ai_only:
                    cmd.append("--prefer_ai")
                    record_stage(current_stage, lambda cmd=cmd: _run(cmd, stage=current_stage))

                    state_path = state_last_ranked(profile)
                    curr = _read_json(ranked_json)
                    prev = _read_json(state_path) if state_path.exists() else []
                    _write_json(state_path, curr)
                    # (diff/alerts handled in full path only; for freshness runs, we just persist state)

            _finalize("success")
            return 0

        # 1) Run pipeline stages ONCE
        current_stage = "scrape"
        record_stage(current_stage, lambda: _run([sys.executable, str(REPO_ROOT / "scripts" / "run_scrape.py"), "--mode", "AUTO"], stage=current_stage))
        
        if args.scrape_only:
            logger.info("Stopping after scrape (--scrape_only set)")
            _finalize("success")
            return 0
        
        current_stage = "classify"
        record_stage(current_stage, lambda: _run([sys.executable, str(REPO_ROOT / "scripts" / "run_classify.py")], stage=current_stage))
        current_stage = "enrich"
        if args.no_enrich:
            logger.info("Skipping enrichment step (--no_enrich set)")
        else:
            record_stage(current_stage, lambda: _run([sys.executable, str(REPO_ROOT / "scripts" / "enrich_jobs.py")], stage=current_stage))

        # Optional AI augment stage
        if args.ai:
            current_stage = "ai_augment"
            telemetry["ai_ran"] = True
            record_stage(current_stage, lambda: _run([sys.executable, str(REPO_ROOT / "scripts" / "run_ai_augment.py")], stage=current_stage))
        # ai_only still proceeds to scoring; we skip the old early-return so scoring can run with AI outputs.

        unavailable_summary = _unavailable_summary()

        # 2–5) For each profile: score -> diff -> state -> optional alert
        for profile in profiles:
            ranked_json = ranked_jobs_json(profile)
            ranked_csv = ranked_jobs_csv(profile)
            ranked_families = ranked_families_json(profile)
            shortlist_md = shortlist_md_path(profile)
            scoring_input_selection_by_profile[profile] = _score_input_selection_detail(args)
            in_path, score_err = _resolve_score_input_path(args)
            scoring_inputs_by_profile[profile] = _file_metadata(in_path) if in_path else {
                "path": None,
                "mtime_iso": None,
                "sha256": None,
            }
            
            # Validate scoring prerequisites
            if score_err or in_path is None:
                logger.error(score_err or "Unknown scoring input error")
                _finalize("error", {"error": score_err or "score input missing", "failed_stage": f"score:{profile}"})
                return 2

            current_stage = f"score:{profile}"
            cmd = [
                sys.executable,
                str(REPO_ROOT / "scripts" / "score_jobs.py"),
                "--profile",
                profile,
                "--in_path",
                str(in_path),
                "--out_json",
                str(ranked_json),
                "--out_csv",
                str(ranked_csv),
                "--out_families",
                str(ranked_families),
                "--out_md",
                str(shortlist_md),
            ] + us_only_flag
            if args.ai or args.ai_only:
                cmd.append("--prefer_ai")

            record_stage(current_stage, lambda cmd=cmd: _run(cmd, stage=current_stage))

            # Warn if freshly produced artifacts are not writable for future runs.
            _warn_if_not_user_writable(
                [
                    ranked_json,
                    ranked_csv,
                    ranked_families,
                    shortlist_md,
                    state_last_ranked(profile),
                ],
                context=f"after_score:{profile}",
            )

            state_path = state_last_ranked(profile)
            state_exists = state_path.exists()
            curr = _read_json(ranked_json)
            prev = _read_json(state_path) if state_exists else []
            new_jobs, changed_jobs, removed_jobs, changed_fields = _diff(prev, curr)

            # Append "Changes since last run" section to shortlist (filtered by min_alert_score)
            _append_shortlist_changes_section(
                shortlist_md,
                profile,
                new_jobs,
                changed_jobs,
                removed_jobs,
                state_exists,
                changed_fields,
                prev_jobs=prev,
                min_alert_score=args.min_alert_score,
            )

            logger.info(
                "Changelog (%s): new=%d changed=%d removed=%d",
                profile,
                len(new_jobs),
                len(changed_jobs),
                len(removed_jobs),
            )
            diff_counts_by_profile[profile] = {
                "new": len(new_jobs),
                "changed": len(changed_jobs),
                "removed": len(removed_jobs),
            }

            _write_json(state_path, curr)

            interesting_new = [j for j in new_jobs if j.get("score", 0) >= args.min_alert_score]
            interesting_changed = [j for j in changed_jobs if j.get("score", 0) >= args.min_alert_score]

            if not webhook:
                logger.info(
                    f"ℹ️ No alerts ({profile}) (new={len(new_jobs)}, changed={len(changed_jobs)}; webhook=unset)."
                )
                if unavailable_summary:
                    logger.info(f"Unavailable reasons: {unavailable_summary}")
                logger.info(f"Done ({profile}). Ranked outputs:\n - {ranked_json}\n - {ranked_csv}\n - {shortlist_md}")
                continue

            if not (interesting_new or interesting_changed):
                logger.info(
                    f"ℹ️ No alerts ({profile}) (new={len(new_jobs)}, changed={len(changed_jobs)}; webhook=set)."
                )
                if unavailable_summary:
                    logger.info(f"Unavailable reasons: {unavailable_summary}")
                logger.info(f"Done ({profile}). Ranked outputs:\n - {ranked_json}\n - {ranked_csv}\n - {shortlist_md}")
                continue

            lines = [f"**Job alerts ({profile})** — {_utcnow_iso()}"]
            if args.us_only:
                lines.append("_US-only filter: ON_")
            lines.append("")

            if interesting_new:
                lines.append(f"🆕 **New high-scoring jobs (>= {args.min_alert_score})**")
                for j in interesting_new[:8]:
                    loc = j.get("location") or j.get("locationName") or ""
                    lines.append(f"- **{j.get('score')}** [{j.get('role_band')}] {j.get('title')} ({loc})")
                    if j.get("apply_url"):
                        lines.append(f"  {j['apply_url']}")
                lines.append("")

            if interesting_changed:
                lines.append(f"♻️ **Changed high-scoring jobs (>= {args.min_alert_score})**")
                for j in interesting_changed[:8]:
                    loc = j.get("location") or j.get("locationName") or ""
                    lines.append(f"- **{j.get('score')}** [{j.get('role_band')}] {j.get('title')} ({loc})")
                    if j.get("apply_url"):
                        lines.append(f"  {j['apply_url']}")
                lines.append("")

            _dispatch_alerts(
                profile,
                webhook,
                new_jobs,
                changed_jobs,
                removed_jobs,
                interesting_new,
                interesting_changed,
                lines,
                args,
                unavailable_summary,
            )

            if unavailable_summary:
                logger.info(f"Unavailable reasons: {unavailable_summary}")
            logger.info(f"Done ({profile}). Ranked outputs:\n - {ranked_json}\n - {ranked_csv}\n - {shortlist_md}")

        _finalize("success")
        return 0

    except subprocess.CalledProcessError as e:
        cmd_str = " ".join(e.cmd) if isinstance(e.cmd, (list, tuple)) else str(e.cmd)
        logger.error(
            f"Stage '{current_stage}' failed (returncode={e.returncode}) cmd={cmd_str}\n"
            f"stdout_tail:\n{(getattr(e, 'output', '') or '')[-4000:]}\n"
            f"stderr_tail:\n{(getattr(e, 'stderr', '') or '')[-4000:]}"
        )
        _post_failure(
            webhook,
            stage=current_stage,
            error=f"{e}\ncmd={cmd_str}",
            no_post=args.no_post,
            stdout=getattr(e, "output", "") or "",
            stderr=getattr(e, "stderr", "") or "",
        )
        _finalize("error", {"error": str(e), "failed_stage": current_stage})
        if e.returncode == 2:
            return 2
        return max(3, e.returncode or 0)
    except SystemExit as e:
        exit_code = _normalize_exit_code(e.code)
        if exit_code == 0:
            raise
        err_msg = str(e) if str(e) else f"Stage '{current_stage}' exited"
        logger.error(
            f"Stage '{current_stage}' raised SystemExit({exit_code}): {err_msg}"
        )
        _post_failure(
            webhook,
            stage=current_stage,
            error=err_msg,
            no_post=args.no_post,
        )
        _finalize("error", {"error": err_msg, "failed_stage": current_stage})
        return exit_code
    except Exception as e:
        logger.error(f"Stage '{current_stage}' failed unexpectedly: {e!r}")
        _post_failure(
            webhook,
            stage=current_stage or "unexpected",
            error=repr(e),
            no_post=args.no_post,
        )
        _finalize("error", {"error": repr(e), "failed_stage": current_stage})
        return 3
    finally:
        logger.info(f"===== jobintel end {_utcnow_iso()} =====")


if __name__ == "__main__":
    raise SystemExit(main())

"""
{
  "run_id": "2026-01-09T18:02:11Z",
  "profiles": ["cs"],
  "flags": {
    "us_only": true,
    "no_enrich": true,
    "ai": false
  },
  "artifacts": {
    "raw": "openai_raw_jobs.json",
    "labeled": "openai_labeled_jobs.json",
    "ranked_cs": "openai_ranked_jobs.cs.json"
  },
  "counts": {
    "scraped": 456,
    "relevant": 10,
    "ranked": 29
  }
}
"""
