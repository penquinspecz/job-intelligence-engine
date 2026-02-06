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

try:
    import _bootstrap  # type: ignore
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

import argparse
import atexit
import importlib
import json
import logging
import os
import platform
import runpy
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ji_engine.config import (
    DATA_DIR,
    ENRICHED_JOBS_JSON,
    HISTORY_DIR,
    LABELED_JOBS_JSON,
    LOCK_PATH,
    RAW_JOBS_JSON,
    REPO_ROOT,
    RUN_METADATA_DIR,
    SNAPSHOT_DIR,
    STATE_DIR,
    ensure_dirs,
    ranked_families_json,
    ranked_jobs_csv,
    ranked_jobs_json,
    state_last_ranked,
)
from ji_engine.config import (
    shortlist_md as shortlist_md_path,
)
from ji_engine.utils.atomic_write import atomic_write_text
from ji_engine.utils.content_fingerprint import content_fingerprint
from ji_engine.utils.diff_report import build_diff_markdown, build_diff_report
from ji_engine.utils.dotenv import load_dotenv
from ji_engine.utils.job_identity import job_identity
from ji_engine.utils.verification import (
    build_verifiable_artifacts,
    compute_sha256_bytes,
    compute_sha256_file,
)
from jobintel.alerts import (
    build_last_seen,
    compute_alerts,
    load_last_seen,
    resolve_score_delta,
    write_alerts,
    write_last_seen,
)
from jobintel.aws_runs import (
    BaselineInfo,
    download_baseline_ranked,
    get_most_recent_successful_run_id_before,
    parse_pointer,
    read_last_success_state,
    read_provider_last_success_state,
    s3_enabled,
)
from jobintel.delta import compute_delta
from jobintel.discord_notify import build_run_summary_message, post_discord, resolve_webhook

OUTPUT_DIR = DATA_DIR

try:
    import scripts.publish_s3 as publish_s3  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - fallback for direct script execution
    import importlib.util

    _spec = importlib.util.spec_from_file_location("publish_s3", REPO_ROOT / "scripts" / "publish_s3.py")
    if _spec and _spec.loader:
        publish_s3 = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(publish_s3)
    else:
        raise


def _unavailable_summary_for(provider: str) -> str:
    enriched_path = _provider_enriched_jobs_json(provider)
    try:
        data = json.loads(enriched_path.read_text(encoding="utf-8"))
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


def _unavailable_summary() -> str:
    return _unavailable_summary_for("openai")


logger = logging.getLogger(__name__)
USE_SUBPROCESS = True
LAST_RUN_JSON = STATE_DIR / "last_run.json"
LAST_SUCCESS_JSON = STATE_DIR / "last_success.json"
RUN_REPORT_SCHEMA_VERSION = 1


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


def _write_canonical_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    path.write_text(payload, encoding="utf-8")


def _update_run_metadata_s3(path: Path, s3_meta: Dict[str, Any]) -> None:
    if not path.exists():
        return
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return
    payload["s3_bucket"] = s3_meta.get("bucket")
    payload["s3_prefixes"] = s3_meta.get("prefixes")
    payload["uploaded_files_count"] = s3_meta.get("uploaded_files_count")
    payload["dashboard_url"] = s3_meta.get("dashboard_url")
    _write_json(path, payload)


def _update_run_metadata_publish(
    path: Path,
    publish_section: Dict[str, Any],
    *,
    success_override: Optional[bool] = None,
    status_override: Optional[str] = None,
) -> None:
    if not path.exists():
        return
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return
    payload["publish"] = publish_section
    if success_override is not None:
        payload["success"] = success_override
    if status_override is not None:
        payload["status"] = status_override
    _write_json(path, payload)


def _pointer_write_ok(pointer_write: Any) -> bool:
    if not isinstance(pointer_write, dict):
        return False
    if pointer_write.get("global") != "ok":
        return False
    provider_status = pointer_write.get("provider_profile", {})
    if isinstance(provider_status, dict):
        return all(status == "ok" for status in provider_status.values())
    return False


def _build_publish_section(
    *,
    s3_meta: Dict[str, Any],
    enabled: bool,
    required: bool,
    bucket: Optional[str],
    prefix: Optional[str],
    skip_reason: Optional[str] = None,
) -> Dict[str, Any]:
    pointer_write = s3_meta.get("pointer_write") if isinstance(s3_meta, dict) else None
    if not pointer_write:
        pointer_write = {"global": "disabled", "provider_profile": {}, "error": None}
    return {
        "enabled": bool(enabled),
        "required": bool(required),
        "bucket": bucket,
        "prefix": prefix,
        "pointer_write": pointer_write,
        "skip_reason": skip_reason,
    }


def _publish_contract_failed(publish_section: Dict[str, Any]) -> bool:
    if not publish_section.get("enabled"):
        return False
    if not publish_section.get("required"):
        return False
    return not _pointer_write_ok(publish_section.get("pointer_write"))


def _resolve_publish_state(
    publish_requested: bool, bucket: str, require_s3: bool = False
) -> Tuple[bool, bool, Optional[str]]:
    if not publish_requested:
        return False, False, None
    if not bucket:
        if require_s3:
            return False, True, "missing_bucket_required"
        return False, False, "skipped_missing_bucket"
    return True, require_s3, None


def _score_meta_path(ranked_json: Path) -> Path:
    return ranked_json.with_suffix(".score_meta.json")


def _scrape_meta_path(provider: str) -> Path:
    return OUTPUT_DIR / f"{provider}_scrape_meta.json"


def _load_scrape_provenance(providers: List[str]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for provider in providers:
        meta_path = _scrape_meta_path(provider)
        if not meta_path.exists() and OUTPUT_DIR != DATA_DIR:
            meta_path = DATA_DIR / f"{provider}_scrape_meta.json"
        if not meta_path.exists():
            continue
        try:
            meta = _read_json(meta_path)
        except Exception:
            continue
        if isinstance(meta, dict):
            out[provider] = meta
    return out


def _get_env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _get_env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _provider_policy_thresholds() -> Dict[str, float]:
    return {
        "error_rate_max": _get_env_float("JOBINTEL_PROVIDER_ERROR_RATE_MAX", 0.25),
        "min_jobs": float(_get_env_int("JOBINTEL_PROVIDER_MIN_JOBS", 1)),
        "min_snapshot_ratio": _get_env_float("JOBINTEL_PROVIDER_MIN_SNAPSHOT_RATIO", 0.2),
    }


def _load_enrich_stats(enriched_path: Path) -> Dict[str, int]:
    stats = {"total": 0, "enriched": 0, "unavailable": 0, "failed": 0}
    if not enriched_path.exists():
        return stats
    try:
        payload = _read_json(enriched_path)
    except Exception:
        return stats
    if not isinstance(payload, list):
        return stats
    for job in payload:
        if not isinstance(job, dict):
            continue
        status = job.get("enrich_status")
        if status == "enriched":
            stats["enriched"] += 1
            stats["total"] += 1
        elif status == "unavailable":
            stats["unavailable"] += 1
            stats["total"] += 1
        elif status == "failed":
            stats["failed"] += 1
            stats["total"] += 1
        else:
            if job.get("jd_text"):
                stats["enriched"] += 1
                stats["total"] += 1
    return stats


def _evaluate_provider_policy(
    provider: str,
    meta: Dict[str, Any],
    *,
    enriched_path: Optional[Path],
    thresholds: Dict[str, float],
    no_enrich: bool,
) -> Tuple[bool, str, str]:
    scrape_mode = (meta.get("scrape_mode") or "").lower()
    parsed_jobs = int(meta.get("parsed_job_count") or 0)
    baseline = meta.get("snapshot_baseline_count")
    baseline_count = int(baseline) if isinstance(baseline, (int, float)) else None

    enrich_stats = _load_enrich_stats(enriched_path) if enriched_path and not no_enrich else {"total": 0}
    error_count = int(enrich_stats.get("unavailable", 0)) + int(enrich_stats.get("failed", 0))
    total = int(enrich_stats.get("total", 0))
    error_rate = (error_count / total) if total > 0 else 0.0

    decision = "ok"
    reason_parts: List[str] = []

    if scrape_mode == "live":
        if parsed_jobs < int(thresholds["min_jobs"]):
            decision = "fail"
            reason_parts.append(f"parsed_jobs<{int(thresholds['min_jobs'])}")
        if baseline_count is not None and baseline_count > 0:
            min_ratio = thresholds["min_snapshot_ratio"]
            if parsed_jobs < int(baseline_count * min_ratio):
                decision = "fail"
                reason_parts.append("parsed_jobs_below_snapshot_ratio")
        if total > 0 and error_rate > thresholds["error_rate_max"]:
            decision = "fail"
            reason_parts.append("enrich_error_rate_exceeded")

    reason = ", ".join(reason_parts) if reason_parts else "ok"
    policy = {
        "decision": decision,
        "reason": reason,
        "scrape_mode": scrape_mode,
        "parsed_job_count": parsed_jobs,
        "snapshot_baseline_count": baseline_count,
        "error_rate": round(error_rate, 4),
        "error_rate_max": thresholds["error_rate_max"],
        "min_jobs": int(thresholds["min_jobs"]),
        "min_snapshot_ratio": thresholds["min_snapshot_ratio"],
        "enrich_stats": enrich_stats,
    }
    meta["failure_policy"] = policy
    line = f"Provider policy ({provider}): {decision} (parsed={parsed_jobs}, error_rate={round(error_rate, 3)})"
    return decision == "fail", reason, line


def _ecs_task_arn_from_metadata() -> Optional[str]:
    metadata_env = ("ECS_CONTAINER_METADATA_URI_V4", "ECS_CONTAINER_METADATA_URI")
    for key in metadata_env:
        base_uri = os.environ.get(key)
        if not base_uri:
            continue
        task_uri = f"{base_uri.rstrip('/')}/task"
        try:
            with urllib.request.urlopen(task_uri, timeout=2) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, json.JSONDecodeError, ValueError):
            continue
        if isinstance(payload, dict):
            task_arn = payload.get("TaskARN") or payload.get("TaskArn")
            if isinstance(task_arn, str) and task_arn:
                return task_arn
    return None


def _resolve_ecs_task_arn() -> str:
    env_value = os.environ.get("JOBINTEL_ECS_TASK_ARN") or os.environ.get("ECS_TASK_ARN")
    if env_value and env_value not in {"unknown", "metadata", "from_metadata"}:
        return env_value
    metadata_value = _ecs_task_arn_from_metadata()
    if metadata_value:
        return metadata_value
    if env_value:
        return env_value
    return "unknown"


def _apply_score_fallback_metadata(selection: Dict[str, Any], ranked_json: Path) -> None:
    meta_path = _score_meta_path(ranked_json)
    if not meta_path.exists():
        return
    try:
        meta = _read_json(meta_path)
    except Exception:
        return
    if isinstance(meta, dict) and meta.get("us_only_fallback"):
        selection["us_only_fallback"] = meta["us_only_fallback"]


def _run_metadata_path(run_id: str) -> Path:
    safe_id = _sanitize_run_id(run_id)
    return RUN_METADATA_DIR / f"{safe_id}.json"


def _sanitize_run_id(run_id: str) -> str:
    return run_id.replace(":", "").replace("-", "").replace(".", "")


def _resolve_providers(args: argparse.Namespace) -> List[str]:
    providers_arg = (args.providers or "").strip()
    providers = [p.strip() for p in providers_arg.split(",") if p.strip()]
    if not providers:
        providers = ["openai"]

    seen = set()
    out: List[str] = []
    for p in providers:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def _resolve_output_dir() -> Path:
    env_value = os.environ.get("JOBINTEL_OUTPUT_DIR")
    if env_value:
        output_dir = Path(env_value).expanduser()
    else:
        output_dir = DATA_DIR / "ashby_cache"
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def _provider_raw_jobs_json(provider: str) -> Path:
    if provider == "openai":
        return RAW_JOBS_JSON
    return OUTPUT_DIR / f"{provider}_raw_jobs.json"


def _provider_labeled_jobs_json(provider: str) -> Path:
    if provider == "openai":
        return LABELED_JOBS_JSON
    return OUTPUT_DIR / f"{provider}_labeled_jobs.json"


def _provider_enriched_jobs_json(provider: str) -> Path:
    if provider == "openai":
        return ENRICHED_JOBS_JSON
    return OUTPUT_DIR / f"{provider}_enriched_jobs.json"


def _alerts_paths(provider: str, profile: str) -> Tuple[Path, Path]:
    return (
        OUTPUT_DIR / f"{provider}_alerts.{profile}.json",
        OUTPUT_DIR / f"{provider}_alerts.{profile}.md",
    )


def _last_seen_path(provider: str, profile: str) -> Path:
    return STATE_DIR / "runs" / "last_seen" / f"{provider}.{profile}.json"


def _provider_ai_jobs_json(provider: str) -> Path:
    if provider == "openai":
        return ENRICHED_JOBS_JSON.with_name("openai_enriched_jobs_ai.json")
    return OUTPUT_DIR / f"{provider}_enriched_jobs_ai.json"


def _provider_ranked_jobs_json(provider: str, profile: str) -> Path:
    if provider == "openai":
        return OUTPUT_DIR / ranked_jobs_json(profile).name
    return OUTPUT_DIR / f"{provider}_ranked_jobs.{profile}.json"


def _provider_ranked_jobs_csv(provider: str, profile: str) -> Path:
    if provider == "openai":
        return OUTPUT_DIR / ranked_jobs_csv(profile).name
    return OUTPUT_DIR / f"{provider}_ranked_jobs.{profile}.csv"


def _provider_ranked_families_json(provider: str, profile: str) -> Path:
    if provider == "openai":
        return OUTPUT_DIR / ranked_families_json(profile).name
    return OUTPUT_DIR / f"{provider}_ranked_families.{profile}.json"


def _provider_shortlist_md(provider: str, profile: str) -> Path:
    if provider == "openai":
        return OUTPUT_DIR / shortlist_md_path(profile).name
    return OUTPUT_DIR / f"{provider}_shortlist.{profile}.md"


def _provider_top_md(provider: str, profile: str) -> Path:
    return OUTPUT_DIR / f"{provider}_top.{profile}.md"


def _provider_diff_paths(provider: str, profile: str) -> Tuple[Path, Path]:
    return (
        OUTPUT_DIR / f"{provider}_diff.{profile}.json",
        OUTPUT_DIR / f"{provider}_diff.{profile}.md",
    )


def _state_last_ranked(provider: str, profile: str) -> Path:
    if provider == "openai":
        return state_last_ranked(profile)
    return STATE_DIR / f"last_ranked.{provider}.{profile}.json"


def _local_last_success_pointer_paths(provider: str, profile: str) -> List[Path]:
    return [
        STATE_DIR / provider / profile / "last_success.json",
        STATE_DIR / "last_success.json",
    ]


def _resolve_local_last_success_ranked(provider: str, profile: str, current_run_id: str) -> Optional[Path]:
    for pointer_path in _local_last_success_pointer_paths(provider, profile):
        if not pointer_path.exists():
            continue
        try:
            payload = json.loads(pointer_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        run_id = parse_pointer(payload) if isinstance(payload, dict) else None
        if not run_id or run_id == current_run_id:
            continue
        run_dir = _run_registry_dir(run_id)
        ranked_path = run_dir / provider / profile / f"{provider}_ranked_jobs.{profile}.json"
        if ranked_path.exists():
            return ranked_path
    return None


def _resolve_latest_run_ranked(provider: str, profile: str, current_run_id: str) -> Optional[Path]:
    if not RUN_METADATA_DIR.exists():
        return None
    candidates: List[Tuple[float, str, Path]] = []
    current_name = _sanitize_run_id(current_run_id)
    for run_dir in RUN_METADATA_DIR.iterdir():
        if not run_dir.is_dir() or run_dir.name == current_name:
            continue
        ranked_path = run_dir / provider / profile / f"{provider}_ranked_jobs.{profile}.json"
        if not ranked_path.exists():
            continue
        report_path = run_dir / "run_report.json"
        try:
            mtime = report_path.stat().st_mtime if report_path.exists() else run_dir.stat().st_mtime
        except OSError:
            continue
        candidates.append((mtime, run_dir.name, ranked_path))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1]))
    return candidates[-1][2]


def _history_run_dir(run_id: str, profile: str, provider: Optional[str] = None) -> Path:
    run_date = run_id.split("T")[0]
    sanitized = _sanitize_run_id(run_id)
    if provider and provider != "openai":
        return HISTORY_DIR / run_date / sanitized / provider / profile
    return HISTORY_DIR / run_date / sanitized / profile


def _latest_profile_dir(profile: str, provider: Optional[str] = None) -> Path:
    if provider and provider != "openai":
        return HISTORY_DIR / "latest" / provider / profile
    return HISTORY_DIR / "latest" / profile


def _copy_artifact(src: Path, dest: Path) -> None:
    if not src.exists():
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)


def _atomic_copy(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".tmp")
    try:
        shutil.copy2(src, tmp)
        os.replace(tmp, dest)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def _archive_input(
    run_dir: Path,
    src: Path,
    dest_rel: Path,
    *,
    state_dir: Path = STATE_DIR,
) -> Dict[str, Any]:
    if not src.exists():
        logger.error("Archive source missing: %s", src)
        raise SystemExit(2)
    dest = run_dir / dest_rel
    try:
        _atomic_copy(src, dest)
        sha256 = compute_sha256_file(dest)
        size = dest.stat().st_size
    except SystemExit:
        raise
    except Exception as exc:
        logger.error("Archive copy failed for %s -> %s: %s", src, dest, exc)
        raise SystemExit(3) from exc
    return {
        "source_path": str(src),
        "archived_path": dest.relative_to(state_dir).as_posix(),
        "sha256": sha256,
        "bytes": size,
        "hash_algo": "sha256",
    }


def _archive_run_inputs(
    run_dir: Path,
    provider: str,
    profile: str,
    selected_input_path: Path,
    profiles_config_path: Path,
) -> Dict[str, Any]:
    base = Path("inputs") / provider / profile
    if not selected_input_path.exists():
        logger.error("Selected scoring input missing for archival: %s", selected_input_path)
        raise SystemExit(2)
    if not profiles_config_path.exists():
        logger.error("Profiles config missing for archival: %s", profiles_config_path)
        raise SystemExit(2)
    return {
        "selected_scoring_input": _archive_input(run_dir, selected_input_path, base / "selected_scoring_input.json"),
        "profile_config": _archive_input(run_dir, profiles_config_path, base / "profiles.json"),
    }


def _run_registry_dir(run_id: str) -> Path:
    return RUN_METADATA_DIR / _sanitize_run_id(run_id)


def _write_run_registry(
    run_id: str,
    providers: List[str],
    profiles: List[str],
    run_metadata_path: Path,
    diff_counts_by_provider: Dict[str, Dict[str, Dict[str, int]]],
    telemetry: Dict[str, Any],
) -> Path:
    run_dir = _run_registry_dir(run_id)
    run_dir.mkdir(parents=True, exist_ok=True)

    artifacts: Dict[str, str] = {}
    run_report_dest = run_dir / "run_report.json"
    _copy_artifact(run_metadata_path, run_report_dest)
    artifacts[run_report_dest.name] = run_report_dest.relative_to(run_dir).as_posix()

    providers_payload: Dict[str, Any] = {}
    for provider in providers:
        provider_dir = run_dir / provider
        provider_payload: Dict[str, Any] = {"profiles": {}, "artifacts": {}}
        provider_inputs = [
            _provider_raw_jobs_json(provider),
            _provider_labeled_jobs_json(provider),
            _provider_enriched_jobs_json(provider),
            _provider_ai_jobs_json(provider),
        ]
        for src in provider_inputs:
            if not src.exists():
                continue
            dest = provider_dir / src.name
            _copy_artifact(src, dest)
            rel = dest.relative_to(run_dir).as_posix()
            provider_payload["artifacts"][src.name] = rel
            artifacts.setdefault(src.name, rel)

        for profile in profiles:
            profile_dir = provider_dir / profile
            profile_payload = {
                "diff_counts": diff_counts_by_provider.get(provider, {}).get(
                    profile, {"new": 0, "changed": 0, "removed": 0}
                ),
                "artifacts": {},
            }
            for src in (run_dir / f"ai_insights.{profile}.json", run_dir / f"ai_insights.{profile}.md"):
                if src.exists():
                    rel = src.relative_to(run_dir).as_posix()
                    profile_payload["artifacts"][src.name] = rel
                    artifacts.setdefault(src.name, rel)
            for src in (run_dir / f"ai_job_briefs.{profile}.json", run_dir / f"ai_job_briefs.{profile}.md"):
                if src.exists():
                    rel = src.relative_to(run_dir).as_posix()
                    profile_payload["artifacts"][src.name] = rel
                    artifacts.setdefault(src.name, rel)
            profile_artifacts = [
                _provider_ranked_jobs_json(provider, profile),
                _provider_ranked_jobs_csv(provider, profile),
                _provider_ranked_families_json(provider, profile),
                _provider_shortlist_md(provider, profile),
                _provider_top_md(provider, profile),
            ]
            alerts_json, alerts_md = _alerts_paths(provider, profile)
            profile_artifacts.extend([alerts_json, alerts_md])

            for src in profile_artifacts:
                if not src.exists():
                    continue
                dest = profile_dir / src.name
                _copy_artifact(src, dest)
                rel = dest.relative_to(run_dir).as_posix()
                profile_payload["artifacts"][src.name] = rel
                artifacts.setdefault(src.name, rel)

            provider_payload["profiles"][profile] = profile_payload

        providers_payload[provider] = provider_payload

    payload = {
        "run_id": run_id,
        "timestamp": telemetry.get("ended_at"),
        "providers": providers_payload,
        "artifacts": artifacts,
        "run_report_path": artifacts.get("run_report.json"),
    }

    index_path = run_dir / "index.json"
    index_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return index_path


def _archive_profile_artifacts(
    run_id: str,
    profile: str,
    run_metadata_path: Path,
    summary_payload: Dict[str, object],
    provider: Optional[str] = None,
) -> None:
    history_dir = _history_run_dir(run_id, profile, provider)
    latest_dir = _latest_profile_dir(profile, provider)
    artifacts = [
        _provider_ranked_jobs_json(provider or "openai", profile),
        _provider_ranked_jobs_csv(provider or "openai", profile),
        _provider_ranked_families_json(provider or "openai", profile),
        _provider_shortlist_md(provider or "openai", profile),
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
    diff_counts: Dict[str, Dict[str, Any]],
    provenance_by_provider: Optional[Dict[str, Dict[str, Any]]],
    scoring_inputs_by_profile: Dict[str, Dict[str, Optional[str]]],
    scoring_input_selection_by_profile: Dict[str, Dict[str, Any]],
    archived_inputs_by_provider_profile: Optional[Dict[str, Dict[str, Dict[str, Any]]]] = None,
    providers: Optional[List[str]] = None,
    inputs_by_provider: Optional[Dict[str, Dict[str, Dict[str, Optional[str]]]]] = None,
    scoring_inputs_by_provider: Optional[Dict[str, Dict[str, Dict[str, Optional[str]]]]] = None,
    scoring_input_selection_by_provider: Optional[Dict[str, Dict[str, Dict[str, Any]]]] = None,
    outputs_by_provider: Optional[Dict[str, Dict[str, Dict[str, Dict[str, Optional[str]]]]]] = None,
    delta_summary: Optional[Dict[str, Any]] = None,
    config_fingerprint: Optional[str] = None,
    environment_fingerprint: Optional[Dict[str, Optional[str]]] = None,
) -> Path:
    run_report_schema_version = RUN_REPORT_SCHEMA_VERSION
    inputs: Dict[str, Dict[str, Optional[str]]] = {
        "raw_jobs_json": _file_metadata(_provider_raw_jobs_json("openai")),
        "labeled_jobs_json": _file_metadata(_provider_labeled_jobs_json("openai")),
        "enriched_jobs_json": _file_metadata(_provider_enriched_jobs_json("openai")),
    }
    ai_path = _provider_ai_jobs_json("openai")
    if ai_path.exists():
        inputs["ai_enriched_jobs_json"] = _file_metadata(ai_path)

    outputs_by_profile: Dict[str, Dict[str, Dict[str, Optional[str]]]] = {}
    for profile in profiles:
        outputs_by_profile[profile] = {
            "ranked_json": _output_metadata(_provider_ranked_jobs_json("openai", profile)),
            "ranked_csv": _output_metadata(_provider_ranked_jobs_csv("openai", profile)),
            "ranked_families_json": _output_metadata(_provider_ranked_families_json("openai", profile)),
            "shortlist_md": _output_metadata(_provider_shortlist_md("openai", profile)),
            "top_md": _output_metadata(_provider_top_md("openai", profile)),
        }

    provider_list = providers or ["openai"]
    provider_inputs = inputs_by_provider or {"openai": inputs}
    provider_scoring_inputs = scoring_inputs_by_provider or {"openai": scoring_inputs_by_profile}
    provider_scoring_selection = scoring_input_selection_by_provider or {"openai": scoring_input_selection_by_profile}
    provider_outputs = outputs_by_provider or {"openai": outputs_by_profile}
    run_dir = RUN_METADATA_DIR / _sanitize_run_id(run_id)
    verifiable_artifacts = _verifiable_artifacts(run_dir, provider_outputs)
    config_fingerprint_value = config_fingerprint or _config_fingerprint(flags, None)
    environment_fingerprint_value = environment_fingerprint or _environment_fingerprint()

    selection = {"scrape_provenance": provenance_by_provider or {}}
    if provenance_by_provider:
        selection["provider_availability"] = {
            provider: {
                "status": meta.get("availability"),
                "unavailable_reason": meta.get("unavailable_reason"),
                "attempts_made": meta.get("attempts_made"),
            }
            for provider, meta in provenance_by_provider.items()
        }
    classified_by_provider = _classified_counts_by_provider(provider_list)
    if classified_by_provider:
        selection["classified_job_count_by_provider"] = classified_by_provider
        if "openai" in classified_by_provider:
            selection["classified_job_count"] = classified_by_provider["openai"]
        else:
            primary_provider = provider_list[0]
            if primary_provider in classified_by_provider:
                selection["classified_job_count"] = classified_by_provider[primary_provider]

    build_provenance = {
        "git_sha": os.environ.get("JOBINTEL_GIT_SHA", "unknown"),
        "image": os.environ.get("JOBINTEL_IMAGE", "unknown"),
        "taskdef": os.environ.get("JOBINTEL_TASKDEF", "unknown"),
        "ecs_task_arn": _resolve_ecs_task_arn(),
    }

    payload = {
        "run_report_schema_version": run_report_schema_version,
        "run_id": run_id,
        "status": telemetry.get("status"),
        "profiles": profiles,
        "providers": provider_list,
        "flags": flags,
        "timestamps": {
            "started_at": telemetry.get("started_at"),
            "ended_at": telemetry.get("ended_at"),
        },
        "stage_durations": telemetry.get("stages", {}),
        "diff_counts": diff_counts,
        "provenance_by_provider": provenance_by_provider or {},
        "provenance": {**(provenance_by_provider or {}), "build": build_provenance},
        "selection": selection,
        "inputs": inputs,
        "scoring_inputs_by_profile": scoring_inputs_by_profile,
        "scoring_input_selection_by_profile": scoring_input_selection_by_profile,
        "outputs_by_profile": outputs_by_profile,
        "inputs_by_provider": provider_inputs,
        "scoring_inputs_by_provider": provider_scoring_inputs,
        "scoring_input_selection_by_provider": provider_scoring_selection,
        "outputs_by_provider": provider_outputs,
        "verifiable_artifacts": verifiable_artifacts,
        "config_fingerprint": config_fingerprint_value,
        "environment_fingerprint": environment_fingerprint_value,
        "git_sha": _best_effort_git_sha(),
        "image_tag": os.environ.get("IMAGE_TAG"),
    }
    if archived_inputs_by_provider_profile:
        payload["archived_inputs_by_provider_profile"] = archived_inputs_by_provider_profile
    if delta_summary is not None:
        payload["delta_summary"] = delta_summary
    payload["success"] = telemetry.get("success", False)
    if telemetry.get("failed_stage"):
        payload["failed_stage"] = telemetry["failed_stage"]
    path = _run_metadata_path(run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return path


def _hash_file(path: Path) -> Optional[str]:
    if not path.exists():
        return None
    try:
        return compute_sha256_file(path)
    except Exception:
        return None


def _count_jobs(path: Path) -> Optional[int]:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if isinstance(data, list):
        return len(data)
    return None


def _classified_counts_by_provider(providers: List[str]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for provider in providers:
        path = _provider_labeled_jobs_json(provider)
        count = _count_jobs(path)
        if count is not None:
            counts[provider] = count
    return counts


def _baseline_latest_dir(provider: str, profile: str) -> Path:
    base_provider = provider if provider != "openai" else None
    return _latest_profile_dir(profile, base_provider)


def _baseline_ranked_path(provider: str, profile: str, baseline_dir: Path) -> Path:
    return baseline_dir / f"{provider}_ranked_jobs.{profile}.json"


def _baseline_run_info(baseline_dir: Path) -> Tuple[Optional[str], Optional[str]]:
    meta_path = baseline_dir / "run_metadata.json"
    if not meta_path.exists():
        return None, None
    try:
        payload = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return None, str(meta_path)
    run_id = payload.get("run_id") if isinstance(payload, dict) else None
    return run_id, str(meta_path)


def _resolve_s3_baseline(
    provider: str,
    profile: str,
    current_run_id: str,
    *,
    bucket: str,
    prefix: str,
) -> BaselineInfo:
    def _warn_missing(run_id: str, source: str) -> None:
        logger.warning(
            "Baseline pointer found (%s) but artifacts missing for %s/%s run_id=%s",
            source,
            provider,
            profile,
            run_id,
        )

    state, status, key = read_provider_last_success_state(bucket, prefix, provider, profile)
    logger.info(
        "Baseline pointer read: s3://%s/%s status=%s",
        bucket,
        key,
        status,
    )
    if isinstance(state, dict):
        run_id = parse_pointer(state)
        if run_id and run_id != current_run_id:
            ranked_path = download_baseline_ranked(
                bucket,
                prefix,
                run_id,
                provider,
                profile,
                STATE_DIR / "baseline_cache",
            )
            if ranked_path:
                logger.info(
                    "Baseline pointer resolved (state_file) for %s/%s run_id=%s",
                    provider,
                    profile,
                    run_id,
                )
                return BaselineInfo(
                    run_id=run_id,
                    source="state_file",
                    path=state.get("run_path") or f"s3://{bucket}/{prefix.strip('/')}/runs/{run_id}/",
                    ranked_path=ranked_path,
                )
            _warn_missing(run_id, "state_file")
    elif status == "access_denied":
        logger.warning(
            "Baseline pointer access denied for %s/%s (s3://%s/%s)",
            provider,
            profile,
            bucket,
            key,
        )

    state, status, key = read_last_success_state(bucket, prefix)
    logger.info(
        "Baseline pointer read: s3://%s/%s status=%s",
        bucket,
        key,
        status,
    )
    if isinstance(state, dict):
        run_id = parse_pointer(state)
        if run_id and run_id != current_run_id:
            ranked_path = download_baseline_ranked(
                bucket,
                prefix,
                run_id,
                provider,
                profile,
                STATE_DIR / "baseline_cache",
            )
            if ranked_path:
                logger.info(
                    "Baseline pointer resolved (state_file) for %s/%s run_id=%s",
                    provider,
                    profile,
                    run_id,
                )
                return BaselineInfo(
                    run_id=run_id,
                    source="state_file",
                    path=state.get("run_path") or f"s3://{bucket}/{prefix.strip('/')}/runs/{run_id}/",
                    ranked_path=ranked_path,
                )
            _warn_missing(run_id, "state_file")
    elif status == "access_denied":
        logger.warning(
            "Baseline pointer access denied for %s/%s (s3://%s/%s)",
            provider,
            profile,
            bucket,
            key,
        )

    logger.info("Baseline pointer fallback: listing s3://%s/%s/runs/", bucket, prefix.strip("/"))
    run_id = get_most_recent_successful_run_id_before(bucket, prefix, current_run_id)
    if run_id:
        ranked_path = download_baseline_ranked(
            bucket,
            prefix,
            run_id,
            provider,
            profile,
            STATE_DIR / "baseline_cache",
        )
        if ranked_path:
            logger.info(
                "Baseline pointer resolved (s3_latest) for %s/%s run_id=%s",
                provider,
                profile,
                run_id,
            )
            return BaselineInfo(
                run_id=run_id,
                source="s3_latest",
                path=f"s3://{bucket}/{prefix.strip('/')}/runs/{run_id}/",
                ranked_path=ranked_path,
            )
        _warn_missing(run_id, "s3_latest")
    return BaselineInfo(run_id=None, source="none", path=None, ranked_path=None)


def _build_delta_summary(run_id: str, providers: List[str], profiles: List[str]) -> Dict[str, Any]:
    summary: Dict[str, Any] = {
        "baseline_run_id": None,
        "baseline_run_path": None,
        "current_run_id": run_id,
        "provider_profile": {},
    }
    first_baseline: Optional[Tuple[str, str]] = None

    for provider in providers:
        summary["provider_profile"].setdefault(provider, {})
        for profile in profiles:
            baseline_dir = _baseline_latest_dir(provider, profile)
            baseline_ranked = _baseline_ranked_path(provider, profile, baseline_dir)
            baseline_run_id, baseline_run_path = _baseline_run_info(baseline_dir)
            baseline_source = "explicit"
            baseline_resolved = baseline_ranked.exists()
            baseline_ranked_path = baseline_ranked if baseline_ranked.exists() else None
            if not baseline_ranked.exists():
                baseline_run_id = None
                baseline_run_path = None
                baseline_source = "none"
                if s3_enabled():
                    bucket = os.environ.get("JOBINTEL_S3_BUCKET", "").strip()
                    prefix = os.environ.get("JOBINTEL_S3_PREFIX", "jobintel").strip("/")
                    if bucket:
                        s3_info = _resolve_s3_baseline(provider, profile, run_id, bucket=bucket, prefix=prefix)
                        if s3_info.run_id and s3_info.ranked_path:
                            baseline_run_id = s3_info.run_id
                            baseline_run_path = s3_info.path
                            baseline_source = s3_info.source
                            baseline_ranked_path = s3_info.ranked_path
                            baseline_resolved = True
                    else:
                        logger.warning("S3 baseline enabled but JOBINTEL_S3_BUCKET is unset.")
            if baseline_run_id and baseline_run_path and first_baseline is None:
                first_baseline = (baseline_run_id, baseline_run_path)

            current_labeled = _provider_labeled_jobs_json(provider)
            current_ranked = _provider_ranked_jobs_json(provider, profile)
            delta = compute_delta(
                current_labeled,
                current_ranked,
                None,
                baseline_ranked_path,
                provider,
                profile,
            )
            delta["baseline_run_id"] = baseline_run_id
            delta["baseline_run_path"] = baseline_run_path
            delta["baseline_source"] = baseline_source
            delta["baseline_resolved"] = baseline_resolved
            delta["current_run_id"] = run_id
            summary["provider_profile"][provider][profile] = delta

    if first_baseline:
        summary["baseline_run_id"], summary["baseline_run_path"] = first_baseline
    return summary


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


def _config_fingerprint(flags: Dict[str, Any], providers_config: Optional[str]) -> str:
    allowed_keys = {
        "profile",
        "profiles",
        "providers",
        "us_only",
        "no_enrich",
        "ai",
        "ai_only",
        "min_score",
        "min_alert_score",
        "offline",
        "scrape_only",
        "no_subprocess",
        "snapshot_only",
    }
    filtered_flags = {key: flags.get(key) for key in sorted(allowed_keys)}
    providers_config_path = Path(providers_config) if providers_config else None
    env_keys = [
        "CAREERS_MODE",
        "EMBED_PROVIDER",
        "EMBEDDING_MODEL",
        "OPENAI_MODEL",
        "ANTHROPIC_MODEL",
        "JOBINTEL_DATA_DIR",
        "JOBINTEL_STATE_DIR",
        "TZ",
        "PYTHONHASHSEED",
    ]
    env_payload = {key: os.environ.get(key) for key in env_keys}
    config_payload = {
        "flags": filtered_flags,
        "providers_config_path": str(providers_config_path) if providers_config_path else None,
        "providers_config_sha256": _hash_file(providers_config_path) if providers_config_path else None,
        "env": env_payload,
    }
    payload = json.dumps(config_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return compute_sha256_bytes(payload.encode("utf-8"))


def _environment_fingerprint() -> Dict[str, Optional[str]]:
    return {
        "python_version": sys.version.split()[0],
        "platform": platform.platform(),
        "image_tag": os.environ.get("IMAGE_TAG"),
        "git_sha": _best_effort_git_sha(),
        "tz": os.environ.get("TZ"),
        "pythonhashseed": os.environ.get("PYTHONHASHSEED"),
    }


def _verifiable_artifacts(
    run_dir: Path, provider_outputs: Dict[str, Dict[str, Dict[str, Dict[str, Optional[str]]]]]
) -> Dict[str, Dict[str, str]]:
    artifacts: Dict[str, Path] = {}
    for provider, profiles_payload in provider_outputs.items():
        for profile, outputs in profiles_payload.items():
            for output_key, meta in outputs.items():
                if not isinstance(meta, dict):
                    continue
                path_str = meta.get("path")
                if not path_str:
                    continue
                logical_key = f"{provider}:{profile}:{output_key}"
                artifacts[logical_key] = Path(path_str)
    return build_verifiable_artifacts(DATA_DIR, artifacts)


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


def _resolve_score_input_path_for(args: argparse.Namespace, provider: str) -> Tuple[Optional[Path], Optional[str]]:
    """
    Decide which input file to feed into score_jobs based on CLI flags.
    Returns (path, error_message). If error_message is not None, caller should abort.
    """
    ai_path = _provider_ai_jobs_json(provider)
    enriched_path = _provider_enriched_jobs_json(provider)
    labeled_path = _provider_labeled_jobs_json(provider)

    if args.ai_only:
        if not ai_path.exists():
            return None, (
                f"AI-only mode requires AI-enriched input at {ai_path}. "
                "Ensure --ai is set and run_ai_augment has produced this file."
            )
        return ai_path, None

    if args.no_enrich:
        # Prefer enriched if it already exists and is newer than labeled; otherwise fall back to labeled.
        enriched_exists = enriched_path.exists()
        labeled_exists = labeled_path.exists()

        if enriched_exists and labeled_exists:
            m_enriched = enriched_path.stat().st_mtime
            m_labeled = labeled_path.stat().st_mtime
            if m_enriched > m_labeled:
                return enriched_path, None
            logger.warning(
                "Enriched input is older than labeled; using labeled for scoring. enriched_mtime=%s labeled_mtime=%s",
                m_enriched,
                m_labeled,
            )
            return labeled_path, None

        if enriched_exists:
            return enriched_path, None
        if labeled_exists:
            return labeled_path, None
        return None, (
            f"Scoring input not found: {enriched_path} or {labeled_path}. "
            "Run without --no_enrich to generate enrichment, or ensure labeled data exists."
        )

    # Default: expect enriched output
    if enriched_path.exists():
        return enriched_path, None

    return None, (f"Scoring input not found: {enriched_path}. Re-run without --no_enrich to produce enrichment output.")


def _score_input_selection_detail_for(args: argparse.Namespace, provider: str) -> Dict[str, Any]:
    ai_path = _provider_ai_jobs_json(provider)
    enriched_path = _provider_enriched_jobs_json(provider)
    labeled_path = _provider_labeled_jobs_json(provider)
    enriched_meta = _candidate_metadata(enriched_path)
    labeled_meta = _candidate_metadata(labeled_path)
    ai_meta = _candidate_metadata(ai_path)
    candidates = [ai_meta, enriched_meta, labeled_meta]
    candidate_paths_considered = candidates
    flags = {"no_enrich": bool(args.no_enrich), "ai": bool(args.ai), "ai_only": bool(args.ai_only)}

    decision: Dict[str, Any] = {"flags": flags, "comparisons": {}}
    selected_path: Optional[Path] = None
    reason = ""
    selection_reason = ""
    comparison_details: Dict[str, Any] = {}
    selection_reason_labeled_vs_enriched = "not_applicable"
    selection_reason_enriched_vs_ai = "not_applicable"
    decision_timestamp = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

    def _selection_reason_detail(
        rule_id: str,
        chosen_path: Optional[Path],
        candidate_paths: List[Path],
        compared_fields: Dict[str, Any],
        decision: str,
    ) -> Dict[str, Any]:
        return {
            "rule_id": rule_id,
            "chosen_path": str(chosen_path) if chosen_path else None,
            "candidate_paths": [str(path) for path in candidate_paths],
            "compared_fields": compared_fields,
            "decision": decision,
            "decision_timestamp": decision_timestamp,
        }

    def _candidate_field_map(paths: List[Path]) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        for path in paths:
            result[str(path)] = _file_metadata(path) if path.exists() else None
        return result

    def _ai_note() -> str:
        if args.ai and not args.ai_only:
            return " (ai does not change selection; prefer_ai affects scoring only)"
        return ""

    if args.ai_only:
        decision["rule"] = "ai_only"
        reason = "ai_only requires AI-enriched input"
        selected_path = ai_path if ai_path.exists() else None
        selection_reason = "ai_only"
        selection_reason_enriched_vs_ai = "ai_only_required"
        decision["reason"] = reason
        labeled_vs_enriched_detail = _selection_reason_detail(
            f"labeled_vs_enriched.{selection_reason_labeled_vs_enriched}",
            None,
            [enriched_path, labeled_path],
            {"candidates": _candidate_field_map([enriched_path, labeled_path])},
            selection_reason_labeled_vs_enriched,
        )
        enriched_vs_ai_detail = _selection_reason_detail(
            f"enriched_vs_ai.{selection_reason_enriched_vs_ai}",
            selected_path,
            [enriched_path, ai_path],
            {"candidates": _candidate_field_map([enriched_path, ai_path])},
            selection_reason_enriched_vs_ai,
        )
        return {
            "selected": _file_metadata(selected_path) if selected_path else None,
            "selected_path": str(selected_path) if selected_path else None,
            "candidate_paths_considered": candidate_paths_considered,
            "selection_reason": selection_reason,
            "selection_reason_labeled_vs_enriched": selection_reason_labeled_vs_enriched,
            "selection_reason_enriched_vs_ai": selection_reason_enriched_vs_ai,
            "selection_reason_details": {
                "labeled_vs_enriched": labeled_vs_enriched_detail,
                "enriched_vs_ai": enriched_vs_ai_detail,
            },
            "comparison_details": comparison_details,
            "candidates": candidates,
            "decision": decision,
        }

    if args.no_enrich:
        decision["rule"] = "no_enrich_compare"
        comparisons: Dict[str, Any] = {}
        if enriched_path.exists() and labeled_path.exists():
            enriched_mtime = _file_mtime(enriched_path)
            labeled_mtime = _file_mtime(labeled_path)
            comparisons["enriched_mtime"] = enriched_mtime
            comparisons["labeled_mtime"] = labeled_mtime
            comparison_details["newer_by_seconds"] = (enriched_mtime or 0) - (labeled_mtime or 0)
            if (enriched_mtime or 0) > (labeled_mtime or 0):
                selected_path = enriched_path
                reason = "enriched newer than labeled"
                selection_reason = "no_enrich_enriched_newer"
                selection_reason_labeled_vs_enriched = "enriched_newer"
                comparisons["winner"] = "enriched"
            else:
                selected_path = labeled_path
                reason = "labeled newer or same mtime as enriched"
                selection_reason = "no_enrich_labeled_newer_or_equal"
                selection_reason_labeled_vs_enriched = "labeled_newer_or_equal"
                comparisons["winner"] = "labeled"
        elif enriched_path.exists():
            selected_path = enriched_path
            reason = "enriched exists and labeled missing"
            selection_reason = "no_enrich_enriched_only"
            selection_reason_labeled_vs_enriched = "enriched_only"
            comparisons["winner"] = "enriched"
        elif labeled_path.exists():
            selected_path = labeled_path
            reason = "labeled exists and enriched missing"
            selection_reason = "no_enrich_labeled_only"
            selection_reason_labeled_vs_enriched = "labeled_only"
            comparisons["winner"] = "labeled"
        else:
            reason = "no_enrich requires labeled or enriched input"
            selection_reason = "no_enrich_missing"
            selection_reason_labeled_vs_enriched = "missing"
        decision["comparisons"] = comparisons
        decision["reason"] = reason + _ai_note()
        base_selected_path = selected_path
        if selected_path == enriched_path and args.ai and ai_path.exists():
            selection_reason = "prefer_ai_enriched"
            selected_path = ai_path
            comparison_details["prefer_ai"] = True
            selection_reason_enriched_vs_ai = "ai_enriched_preferred"
        elif selected_path == enriched_path and args.ai:
            selection_reason_enriched_vs_ai = "ai_enriched_missing"
        labeled_vs_enriched_detail = _selection_reason_detail(
            f"labeled_vs_enriched.{selection_reason_labeled_vs_enriched}",
            base_selected_path,
            [enriched_path, labeled_path],
            {
                "candidates": _candidate_field_map([enriched_path, labeled_path]),
                "comparisons": comparisons,
            },
            selection_reason_labeled_vs_enriched,
        )
        enriched_vs_ai_detail = _selection_reason_detail(
            f"enriched_vs_ai.{selection_reason_enriched_vs_ai}",
            selected_path,
            [enriched_path, ai_path],
            {"candidates": _candidate_field_map([enriched_path, ai_path])},
            selection_reason_enriched_vs_ai,
        )
        return {
            "selected": _file_metadata(selected_path) if selected_path else None,
            "selected_path": str(selected_path) if selected_path else None,
            "candidate_paths_considered": candidate_paths_considered,
            "selection_reason": selection_reason,
            "selection_reason_labeled_vs_enriched": selection_reason_labeled_vs_enriched,
            "selection_reason_enriched_vs_ai": selection_reason_enriched_vs_ai,
            "selection_reason_details": {
                "labeled_vs_enriched": labeled_vs_enriched_detail,
                "enriched_vs_ai": enriched_vs_ai_detail,
            },
            "comparison_details": comparison_details,
            "candidates": candidates,
            "decision": decision,
        }

    decision["rule"] = "default_enriched_required"
    if enriched_path.exists():
        selected_path = enriched_path
        reason = "default requires enriched input"
        selection_reason = "default_enriched_required"
        selection_reason_labeled_vs_enriched = "enriched_required"
    else:
        reason = "enriched input missing"
        selection_reason = "default_enriched_missing"
        selection_reason_labeled_vs_enriched = "missing"
    decision["reason"] = reason + _ai_note()
    base_selected_path = selected_path
    if selected_path == enriched_path and args.ai and ai_path.exists():
        selection_reason = "prefer_ai_enriched"
        selected_path = ai_path
        comparison_details["prefer_ai"] = True
        selection_reason_enriched_vs_ai = "ai_enriched_preferred"
    elif selected_path == enriched_path and args.ai:
        selection_reason_enriched_vs_ai = "ai_enriched_missing"
    labeled_vs_enriched_detail = _selection_reason_detail(
        f"labeled_vs_enriched.{selection_reason_labeled_vs_enriched}",
        base_selected_path,
        [enriched_path, labeled_path],
        {"candidates": _candidate_field_map([enriched_path, labeled_path])},
        selection_reason_labeled_vs_enriched,
    )
    enriched_vs_ai_detail = _selection_reason_detail(
        f"enriched_vs_ai.{selection_reason_enriched_vs_ai}",
        selected_path,
        [enriched_path, ai_path],
        {"candidates": _candidate_field_map([enriched_path, ai_path])},
        selection_reason_enriched_vs_ai,
    )
    return {
        "selected": _file_metadata(selected_path) if selected_path else None,
        "selected_path": str(selected_path) if selected_path else None,
        "candidate_paths_considered": candidate_paths_considered,
        "selection_reason": selection_reason,
        "selection_reason_labeled_vs_enriched": selection_reason_labeled_vs_enriched,
        "selection_reason_enriched_vs_ai": selection_reason_enriched_vs_ai,
        "selection_reason_details": {
            "labeled_vs_enriched": labeled_vs_enriched_detail,
            "enriched_vs_ai": enriched_vs_ai_detail,
        },
        "comparison_details": comparison_details,
        "candidates": candidates,
        "decision": decision,
    }


def _resolve_score_input_path(args: argparse.Namespace) -> Tuple[Optional[Path], Optional[str]]:
    return _resolve_score_input_path_for(args, "openai")


def _score_input_selection_detail(args: argparse.Namespace) -> Dict[str, Any]:
    return _score_input_selection_detail_for(args, "openai")


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


def _parse_logical_key(logical_key: str) -> Optional[Tuple[str, str, str]]:
    parts = logical_key.split(":")
    if len(parts) < 3:
        return None
    provider, profile = parts[0], parts[1]
    output_key = ":".join(parts[2:])
    return provider, profile, output_key


def _build_last_success_pointer(run_report: Dict[str, Any], run_report_path: Path) -> Dict[str, Any]:
    verifiable = run_report.get("verifiable_artifacts") if isinstance(run_report, dict) else None
    artifacts: Dict[str, Dict[str, Any]] = {}
    provider_profile: Dict[str, Dict[str, Dict[str, Any]]] = {}
    if isinstance(verifiable, dict):
        for logical_key, meta in verifiable.items():
            if not isinstance(meta, dict):
                continue
            sha = meta.get("sha256")
            bytes_value = meta.get("bytes")
            artifacts[logical_key] = {"sha256": sha, "bytes": bytes_value}
            parsed = _parse_logical_key(logical_key)
            if parsed:
                provider, profile, _ = parsed
                provider_profile.setdefault(provider, {}).setdefault(profile, {})[logical_key] = sha

    timestamps = run_report.get("timestamps") if isinstance(run_report, dict) else None
    completed_at = None
    if isinstance(timestamps, dict):
        completed_at = timestamps.get("ended_at")
    if not completed_at:
        completed_at = run_report.get("timestamp") if isinstance(run_report, dict) else None

    return {
        "run_id": run_report.get("run_id") if isinstance(run_report, dict) else None,
        "completed_at_utc": completed_at,
        "providers": run_report.get("providers") if isinstance(run_report, dict) else None,
        "profiles": run_report.get("profiles") if isinstance(run_report, dict) else None,
        "provider_profile": provider_profile,
        "artifacts": artifacts,
        "run_report_path": str(run_report_path),
    }


def _write_last_success_pointer(run_report: Dict[str, Any], run_report_path: Path) -> None:
    payload = _build_last_success_pointer(run_report, run_report_path)
    LAST_SUCCESS_JSON.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(
        LAST_SUCCESS_JSON,
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
    )


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
        job.get("description_text") or job.get("jd_text") or job.get("description") or job.get("descriptionHtml") or ""
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
    return str(job.get("content_fingerprint") or content_fingerprint(job))


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


def _diff_summary_entry(
    *,
    run_id: str,
    provider: str,
    profile: str,
    diff_report: Dict[str, Any],
) -> Dict[str, Any]:
    added_ids = sorted({item.get("id") for item in diff_report.get("added") or [] if item.get("id")})
    changed_ids = sorted({item.get("id") for item in diff_report.get("changed") or [] if item.get("id")})
    removed_ids = sorted({item.get("id") for item in diff_report.get("removed") or [] if item.get("id")})
    counts = diff_report.get("counts") or {}
    return {
        "run_id": run_id,
        "provider": provider,
        "profile": profile,
        "first_run": not bool(diff_report.get("baseline_exists")),
        "prior_run_id": None,
        "baseline_resolved": None,
        "baseline_source": None,
        "counts": {
            "new": counts.get("added", 0),
            "changed": counts.get("changed", 0),
            "removed": counts.get("removed", 0),
        },
        "new_ids": added_ids,
        "changed_ids": changed_ids,
        "removed_ids": removed_ids,
        "summary_hash": diff_report.get("summary_hash"),
    }


def _write_diff_summary(run_dir: Path, payload: Dict[str, Any]) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    json_path = run_dir / "diff_summary.json"
    md_path = run_dir / "diff_summary.md"
    _write_canonical_json(json_path, payload)
    lines = ["# Diff Summary"]
    provider_profile = payload.get("provider_profile") or {}
    for provider in sorted(provider_profile):
        profiles = provider_profile.get(provider) or {}
        for profile in sorted(profiles):
            entry = profiles.get(profile) or {}
            counts = entry.get("counts") or {}
            label = f"{provider}:{profile}"
            lines.append(
                f"- {label}: new={counts.get('new', 0)} changed={counts.get('changed', 0)} removed={counts.get('removed', 0)}"
            )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


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
        logger.info(f"ℹ️ No alerts ({profile}) (new={len(new_jobs)}, changed={len(changed_jobs)}; webhook=unset).")
        return

    if not (interesting_new or interesting_changed):
        logger.info(f"ℹ️ No alerts ({profile}) (new={len(new_jobs)}, changed={len(changed_jobs)}; webhook=set).")
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
    logger.info(f"✅ Discord alert sent ({profile})." if ok else "⚠️ Discord alert NOT sent (pipeline still completed).")


def _resolve_notify_mode(raw_mode: Optional[str]) -> str:
    if os.environ.get("JOBINTEL_DISCORD_ALWAYS_POST", "").strip() == "1":
        return "always"
    mode = (raw_mode or "diff").strip().lower()
    if mode not in {"diff", "always"}:
        return "diff"
    return mode


def _should_notify(diff_counts: Dict[str, Any], mode: str) -> bool:
    if diff_counts.get("suppressed") is True:
        return False
    if mode == "always":
        return True
    if diff_counts.get("first_run") is True:
        return True
    return any(diff_counts.get(k, 0) > 0 for k in ("new", "changed", "removed"))


def _maybe_post_run_summary(
    provider: str,
    profile: str,
    ranked_json: Path,
    diff_counts: Dict[str, Any],
    min_score: int,
    *,
    notify_mode: str,
    no_post: bool,
    extra_lines: Optional[List[str]] = None,
) -> str:
    if not _should_notify(diff_counts, notify_mode):
        logger.info("Discord notify skipped (mode=%s, no diffs).", notify_mode)
        return "skipped"
    return _post_run_summary(
        provider,
        profile,
        ranked_json,
        diff_counts,
        min_score,
        no_post=no_post,
        extra_lines=extra_lines,
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
            logger.warning(
                "⚠️ Discord says: Unknown Webhook (rotated/deleted/wrong URL). Update DISCORD_WEBHOOK_URL in .env."
            )
        return False
    except Exception as e:
        logger.error(f"Discord webhook POST failed: {e!r}")
        return False


def _post_failure(
    webhook_url: str, stage: str, error: str, no_post: bool, *, stdout: str = "", stderr: str = ""
) -> None:
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


def _post_run_summary(
    provider: str,
    profile: str,
    ranked_json: Path,
    diff_counts: Dict[str, int],
    min_score: int,
    *,
    no_post: bool,
    extra_lines: Optional[List[str]] = None,
) -> str:
    if no_post:
        return "disabled"
    webhook = resolve_webhook(profile)
    if not webhook:
        logger.info("Discord webhook unset; skipping run summary alert.")
        return "unset"
    if "discord.com/api/webhooks/" not in webhook:
        logger.warning("⚠️ DISCORD_WEBHOOK_URL missing or doesn't look like a Discord webhook URL. Skipping post.")
        return "invalid"
    message = build_run_summary_message(
        provider=provider,
        profile=profile,
        ranked_json=ranked_json,
        diff_counts=diff_counts,
        min_score=min_score,
        extra_lines=extra_lines,
    )
    ok = post_discord(webhook, message)
    return "ok" if ok else "failed"


def _briefs_status_line(run_id: str, profile: str) -> Optional[str]:
    run_dir = RUN_METADATA_DIR / _sanitize_run_id(run_id)
    path = run_dir / f"ai_job_briefs.{profile}.json"
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    count = len(payload.get("briefs") or [])
    status = payload.get("status") or "unknown"
    if status != "ok":
        return f"AI briefs: {status}"
    return f"AI briefs: generated for top {count}"


def _all_providers_unavailable(provenance_by_provider: Dict[str, Dict[str, Any]], providers: List[str]) -> bool:
    if not providers:
        return False
    for provider in providers:
        meta = provenance_by_provider.get(provider) or {}
        if meta.get("availability") != "unavailable":
            return False
    return True


def _provider_unavailable_line(provider: str, meta: Dict[str, Any]) -> Optional[str]:
    if meta.get("availability") != "unavailable":
        return None
    reason = meta.get("unavailable_reason") or "unknown"
    attempts = meta.get("attempts_made")
    if attempts is None:
        return f"Provider unavailable: {provider} ({reason})"
    return f"Provider unavailable: {provider} ({reason}, attempts={attempts})"


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
    ensure_dirs()
    ap = argparse.ArgumentParser()

    ap.add_argument("--profile", default="cs", help="Scoring profile name (cs|tam|se)")
    ap.add_argument(
        "--profiles",
        default="",
        help="Comma-separated profiles to run (e.g. cs or cs,tam,se). If set, overrides --profile.",
    )
    ap.add_argument(
        "--providers",
        default="openai",
        help="Comma-separated provider ids to run (default: openai).",
    )
    ap.add_argument(
        "--providers-config",
        default=str(Path("config") / "providers.json"),
        help="Path to providers config JSON.",
    )
    ap.add_argument("--us_only", action="store_true")
    ap.add_argument("--min_alert_score", type=int, default=85)
    ap.add_argument("--min_score", type=int, default=40, help="Shortlist minimum score threshold.")
    ap.add_argument("--offline", action="store_true", help="Force snapshot mode (no live scraping).")
    ap.add_argument(
        "--snapshot-only",
        action="store_true",
        help="Fail if any provider would use live scraping; enforce snapshot-only determinism.",
    )
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
    ap.add_argument("--publish-s3", action="store_true", help="Publish run artifacts to S3 after completion.")
    ap.add_argument(
        "--publish-dry-run",
        action="store_true",
        help="Plan S3 publish without uploading (requires --publish-s3 or implies it).",
    )

    args = ap.parse_args()
    if args.snapshot_only and not args.offline:
        args.offline = True
    global OUTPUT_DIR, RAW_JOBS_JSON, LABELED_JOBS_JSON, ENRICHED_JOBS_JSON
    OUTPUT_DIR = _resolve_output_dir()
    os.environ.setdefault("JOBINTEL_OUTPUT_DIR", str(OUTPUT_DIR))
    if RAW_JOBS_JSON.parent != OUTPUT_DIR:
        RAW_JOBS_JSON = OUTPUT_DIR / RAW_JOBS_JSON.name
        LABELED_JOBS_JSON = OUTPUT_DIR / LABELED_JOBS_JSON.name
        ENRICHED_JOBS_JSON = OUTPUT_DIR / ENRICHED_JOBS_JSON.name
    providers = _resolve_providers(args)
    openai_only = providers == ["openai"]
    run_id = _utcnow_iso()
    print(f"JOBINTEL_RUN_ID={run_id}", flush=True)
    global USE_SUBPROCESS
    USE_SUBPROCESS = not args.no_subprocess
    _setup_logging(args.log_json)
    webhook = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    notify_mode = _resolve_notify_mode(os.environ.get("DISCORD_NOTIFY_MODE"))

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
        "raw": _hash_file(_provider_raw_jobs_json("openai")),
        "labeled": _hash_file(_provider_labeled_jobs_json("openai")),
        "enriched": _hash_file(_provider_enriched_jobs_json("openai")),
    }
    ai_path = _provider_ai_jobs_json("openai")
    ai_hash = _hash_file(ai_path)
    ai_mtime = _file_mtime(ai_path)

    profiles_list: List[str] = []
    diff_counts_by_profile: Dict[str, Dict[str, Any]] = {}
    scoring_inputs_by_profile: Dict[str, Dict[str, Optional[str]]] = {}
    scoring_input_selection_by_profile: Dict[str, Dict[str, Any]] = {}
    diff_counts_by_provider: Dict[str, Dict[str, Dict[str, Any]]] = {}
    diff_summary_by_provider_profile: Dict[str, Dict[str, Dict[str, Any]]] = {}
    scoring_inputs_by_provider: Dict[str, Dict[str, Dict[str, Optional[str]]]] = {}
    scoring_input_selection_by_provider: Dict[str, Dict[str, Dict[str, Any]]] = {}
    archived_inputs_by_provider_profile: Dict[str, Dict[str, Dict[str, Any]]] = {}
    provenance_by_provider: Dict[str, Dict[str, Any]] = {}
    discord_status_by_provider: Dict[str, Dict[str, str]] = {}
    provider_policy_lines: Dict[str, str] = {}
    flag_payload = {
        "profile": args.profile,
        "profiles": args.profiles,
        "providers": providers,
        "us_only": args.us_only,
        "no_enrich": args.no_enrich,
        "ai": args.ai,
        "ai_only": args.ai_only,
        "min_score": args.min_score,
        "min_alert_score": args.min_alert_score,
        "snapshot_only": args.snapshot_only,
        "publish_s3": args.publish_s3,
        "publish_dry_run": args.publish_dry_run,
    }

    def _finalize(status: str, extra: Optional[Dict[str, Any]] = None) -> None:
        telemetry["status"] = status
        telemetry["hashes"] = {
            "raw": _hash_file(_provider_raw_jobs_json("openai")),
            "labeled": _hash_file(_provider_labeled_jobs_json("openai")),
            "enriched": _hash_file(_provider_enriched_jobs_json("openai")),
        }
        telemetry["counts"] = {
            "raw": _safe_len(_provider_raw_jobs_json("openai")),
            "labeled": _safe_len(_provider_labeled_jobs_json("openai")),
            "enriched": _safe_len(_provider_enriched_jobs_json("openai")),
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
        provider_inputs: Dict[str, Dict[str, Dict[str, Optional[str]]]] = {}
        provider_outputs: Dict[str, Dict[str, Dict[str, Dict[str, Optional[str]]]]] = {}
        for provider in providers:
            inputs: Dict[str, Dict[str, Optional[str]]] = {
                "raw_jobs_json": _file_metadata(_provider_raw_jobs_json(provider)),
                "labeled_jobs_json": _file_metadata(_provider_labeled_jobs_json(provider)),
                "enriched_jobs_json": _file_metadata(_provider_enriched_jobs_json(provider)),
            }
            ai_path_local = _provider_ai_jobs_json(provider)
            if ai_path_local.exists():
                inputs["ai_enriched_jobs_json"] = _file_metadata(ai_path_local)
            provider_inputs[provider] = inputs

            outputs_for_provider: Dict[str, Dict[str, Dict[str, Optional[str]]]] = {}
            for profile in profiles_list:
                outputs_for_provider[profile] = {
                    "ranked_json": _output_metadata(_provider_ranked_jobs_json(provider, profile)),
                    "ranked_csv": _output_metadata(_provider_ranked_jobs_csv(provider, profile)),
                    "ranked_families_json": _output_metadata(_provider_ranked_families_json(provider, profile)),
                    "shortlist_md": _output_metadata(_provider_shortlist_md(provider, profile)),
                    "top_md": _output_metadata(_provider_top_md(provider, profile)),
                }
            provider_outputs[provider] = outputs_for_provider

        config_fingerprint = _config_fingerprint(flag_payload, args.providers_config)
        environment_fingerprint = _environment_fingerprint()
        delta_summary = _build_delta_summary(run_id, providers, profiles_list)
        for provider, profiles in diff_summary_by_provider_profile.items():
            for profile, entry in profiles.items():
                delta = delta_summary.get("provider_profile", {}).get(provider, {}).get(profile, {})
                entry["prior_run_id"] = delta.get("baseline_run_id")
                entry["baseline_resolved"] = delta.get("baseline_resolved")
                entry["baseline_source"] = delta.get("baseline_source")
        run_dir = RUN_METADATA_DIR / _sanitize_run_id(run_id)
        if diff_summary_by_provider_profile:
            _write_diff_summary(
                run_dir,
                {
                    "run_id": run_id,
                    "generated_at": _utcnow_iso(),
                    "provider_profile": diff_summary_by_provider_profile,
                },
            )
        run_metadata_path = _persist_run_metadata(
            run_id,
            telemetry,
            profiles_list,
            flag_payload,
            diff_counts_by_profile,
            provenance_by_provider,
            scoring_inputs_by_profile,
            scoring_input_selection_by_profile,
            archived_inputs_by_provider_profile=archived_inputs_by_provider_profile,
            providers=providers,
            inputs_by_provider=provider_inputs,
            scoring_inputs_by_provider=scoring_inputs_by_provider,
            scoring_input_selection_by_provider=scoring_input_selection_by_provider,
            outputs_by_provider=provider_outputs,
            delta_summary=delta_summary,
            config_fingerprint=config_fingerprint,
            environment_fingerprint=environment_fingerprint,
        )
        if telemetry.get("success", False):
            try:
                run_report_payload = json.loads(run_metadata_path.read_text(encoding="utf-8"))
                if isinstance(run_report_payload, dict):
                    _write_last_success_pointer(run_report_payload, run_metadata_path)
            except Exception as exc:
                logger.warning("Failed to write last_success pointer: %r", exc)
        if openai_only:
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
        else:
            for provider in providers:
                for profile in profiles_list:
                    diffs = diff_counts_by_provider.get(provider, {}).get(
                        profile, {"new": 0, "changed": 0, "removed": 0}
                    )
                    summary_payload = {
                        "run_id": run_id,
                        "timestamp": telemetry["ended_at"],
                        "profile": profile,
                        "provider": provider,
                        "flags": flag_payload,
                        "short_circuit": telemetry["status"] == "short_circuit",
                        "diff_counts": diffs,
                    }
                    _archive_profile_artifacts(
                        run_id,
                        profile,
                        run_metadata_path,
                        summary_payload,
                        provider=provider,
                    )

        _write_run_registry(
            run_id,
            providers,
            profiles_list,
            run_metadata_path,
            diff_counts_by_provider,
            telemetry,
        )

        s3_meta: Dict[str, Any] = {"status": "disabled"}
        s3_failed = False
        s3_exit_code: Optional[int] = None
        dry_run = False
        publish_requested_env = os.environ.get("PUBLISH_S3", "0").strip() == "1"
        publish_requested_cli = bool(args.publish_s3 or args.publish_dry_run)
        publish_requested = publish_requested_env or publish_requested_cli
        publish_required_env = (
            os.environ.get("PUBLISH_S3_REQUIRE", "0").strip() == "1"
            or os.environ.get("JOBINTEL_PUBLISH_REQUIRE", "0").strip() == "1"
        )
        publish_required = publish_required_env
        resolved_bucket, resolved_prefix = publish_s3._resolve_bucket_prefix(None, None)
        publish_enabled, require_s3, skip_reason = _resolve_publish_state(
            publish_requested, resolved_bucket, publish_required
        )
        if status != "success":
            skip_reason = f"skipped_status_{status}"
            publish_enabled = False
            require_s3 = False
            s3_meta = {"status": "skipped", "reason": skip_reason}
        elif skip_reason:
            if skip_reason == "missing_bucket_required":
                err = "S3 publish required but JOBINTEL_S3_BUCKET is unset."
                logger.error(err)
                s3_meta = {"status": "error", "reason": "missing_bucket", "error": err}
                s3_exit_code = 2
                s3_failed = True
            else:
                logger.warning("S3 publish requested but bucket is unset; skipping.")
                s3_meta = {"status": "skipped", "reason": skip_reason}

        if publish_enabled:
            dry_run = bool(args.publish_dry_run) or os.environ.get("PUBLISH_S3_DRY_RUN", "0").strip() == "1"
            logger.info(
                "S3 publish enabled: s3://%s/%s (dry_run=%s require=%s)",
                resolved_bucket,
                resolved_prefix,
                dry_run,
                require_s3,
            )
            try:
                preflight = publish_s3._run_preflight(
                    bucket=None,
                    region=None,
                    prefix=None,
                    dry_run=dry_run,
                )
                if not preflight.get("ok"):
                    logger.error("AWS preflight failed: %s", ", ".join(preflight.get("errors", [])))
                    s3_meta = {"status": "error", "reason": "preflight_failed", "preflight": preflight}
                    s3_exit_code = 2
                    s3_failed = require_s3
                else:
                    s3_meta = publish_s3.publish_run(
                        run_id=run_id,
                        bucket=None,
                        prefix=None,
                        run_dir=RUN_METADATA_DIR / publish_s3._sanitize_run_id(run_id),
                        dry_run=dry_run,
                        require_s3=require_s3,
                        providers=providers,
                        profiles=profiles_list,
                        write_last_success=bool(telemetry.get("success", False)),
                    )
                    if isinstance(s3_meta, dict) and s3_meta.get("status") == "ok":
                        _update_run_metadata_s3(run_metadata_path, s3_meta)
            except SystemExit as exc:
                s3_meta = {"status": "error", "reason": "publish_failed"}
                s3_exit_code = _normalize_exit_code(exc.code)
                s3_failed = require_s3
            except Exception as exc:
                s3_meta = {"status": "error", "reason": f"publish_failed:{exc.__class__.__name__}"}
                s3_exit_code = 2
                s3_failed = require_s3
        else:
            if publish_requested and skip_reason:
                logger.info("S3 publish skipped (%s).", skip_reason)
            elif not publish_requested:
                logger.info("S3 publish not requested (PUBLISH_S3 != 1).")
            else:
                logger.info("S3 publish disabled.")

        required_contract = require_s3 and not dry_run
        publish_section = _build_publish_section(
            s3_meta=s3_meta,
            enabled=publish_enabled,
            required=required_contract,
            bucket=resolved_bucket or None,
            prefix=resolved_prefix or None,
            skip_reason=skip_reason,
        )
        if _publish_contract_failed(publish_section):
            s3_failed = True
            s3_exit_code = s3_exit_code or 2
            _update_run_metadata_publish(
                run_metadata_path,
                publish_section,
                success_override=False,
                status_override="failed",
            )
        else:
            _update_run_metadata_publish(run_metadata_path, publish_section)
        logger.info(
            "PUBLISH_CONTRACT enabled=%s required=%s bucket=%s prefix=%s pointer_global=%s pointer_profiles=%s error=%s",
            publish_section.get("enabled"),
            publish_section.get("required"),
            publish_section.get("bucket"),
            publish_section.get("prefix"),
            (publish_section.get("pointer_write") or {}).get("global"),
            json.dumps((publish_section.get("pointer_write") or {}).get("provider_profile", {}), sort_keys=True),
            (publish_section.get("pointer_write") or {}).get("error"),
        )

        if os.environ.get("JOBINTEL_PRUNE") == "1":
            try:
                from scripts import prune_state as prune_state

                prune_state.main(["--apply"])
            except Exception as e:
                logger.warning("Prune step failed (JOBINTEL_PRUNE=1): %r", e)

        s3_prefixes = s3_meta.get("prefixes") if isinstance(s3_meta, dict) else None
        dashboard_url = None
        if isinstance(s3_meta, dict):
            dashboard_url = s3_meta.get("dashboard_url")
        if not dashboard_url:
            env_dashboard = os.environ.get("JOBINTEL_DASHBOARD_URL", "").strip().rstrip("/")
            if env_dashboard:
                dashboard_url = f"{env_dashboard}/runs/{run_id}"

        provider_availability = {}
        for provider in providers:
            meta = provenance_by_provider.get(provider, {})
            provider_availability[provider] = {
                "status": meta.get("availability") or "unknown",
                "unavailable_reason": meta.get("unavailable_reason"),
                "attempts_made": meta.get("attempts_made"),
            }

        logger.info(
            "RUN SUMMARY\n"
            "run_id=%s\n"
            "providers=%s\n"
            "profiles=%s\n"
            "s3_status=%s\n"
            "s3_reason=%s\n"
            "s3_bucket=%s\n"
            "s3_prefixes=%s\n"
            "dashboard_url=%s\n"
            "discord_status=%s\n"
            "provider_availability=%s",
            run_id,
            ",".join(providers),
            ",".join(profiles_list),
            s3_meta.get("status", "unknown") if isinstance(s3_meta, dict) else "unknown",
            s3_meta.get("reason") if isinstance(s3_meta, dict) else None,
            s3_meta.get("bucket") if isinstance(s3_meta, dict) else None,
            json.dumps(s3_prefixes, sort_keys=True) if s3_prefixes else None,
            dashboard_url,
            json.dumps(discord_status_by_provider, sort_keys=True) if discord_status_by_provider else None,
            json.dumps(provider_availability, sort_keys=True),
        )
        if s3_failed:
            raise SystemExit(s3_exit_code or 2)

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
        warn_paths: List[Path] = [DATA_DIR / "ashby_cache", STATE_DIR, LAST_RUN_JSON, Path("/tmp"), Path("/work")]
        for provider in providers:
            warn_paths.extend(
                [
                    _provider_raw_jobs_json(provider),
                    _provider_labeled_jobs_json(provider),
                    _provider_enriched_jobs_json(provider),
                    _provider_ai_jobs_json(provider),
                ]
            )
        _warn_if_not_user_writable(warn_paths, context="startup")

        # Snapshot presence check (fail fast with alert if missing and needed)
        if "openai" in providers:
            snapshot_path = SNAPSHOT_DIR / "index.html"
            if not snapshot_path.exists():
                msg = (
                    f"Snapshot not found at {snapshot_path}. "
                    "Save https://openai.com/careers/search/ to data/openai_snapshots/index.html or switch mode."
                )
                raise RuntimeError(msg)

        # Short-circuit check (ai-aware) for openai-only runs.
        base_short = openai_only and _should_short_circuit(prev_hashes, curr_hashes)

        def _ranked_up_to_date() -> bool:
            if ai_mtime is None:
                return False
            for p in profiles:
                rjson = _provider_ranked_jobs_json("openai", p)
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
                    ranked_json = _provider_ranked_jobs_json("openai", p)
                    ranked_csv = _provider_ranked_jobs_csv("openai", p)
                    ranked_families = _provider_ranked_families_json("openai", p)
                    shortlist_md = _provider_shortlist_md("openai", p)
                    if not ranked_json.exists():
                        missing_artifacts.append(ranked_json)
                    if not ranked_csv.exists():
                        missing_artifacts.append(ranked_csv)
                    if not ranked_families.exists():
                        missing_artifacts.append(ranked_families)
                    if not shortlist_md.exists():
                        missing_artifacts.append(shortlist_md)

                if not missing_artifacts:
                    telemetry["hashes"] = curr_hashes
                    telemetry["counts"] = {
                        "raw": _safe_len(_provider_raw_jobs_json("openai")),
                        "labeled": _safe_len(_provider_labeled_jobs_json("openai")),
                        "enriched": _safe_len(_provider_enriched_jobs_json("openai")),
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
                (ai_hash is not None and ai_hash == prev_ai_hash)
                or (curr_ai_mtime_iso is not None and curr_ai_mtime_iso == prev_ai_mtime)
            )

            if ai_fresh and prev_ai_ran and _ranked_up_to_date():
                telemetry["hashes"] = curr_hashes
                telemetry["counts"] = {
                    "raw": _safe_len(_provider_raw_jobs_json("openai")),
                    "labeled": _safe_len(_provider_labeled_jobs_json("openai")),
                    "enriched": _safe_len(_provider_enriched_jobs_json("openai")),
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
                    lambda: _run(
                        [sys.executable, str(REPO_ROOT / "scripts" / "run_ai_augment.py")], stage=current_stage
                    ),
                )
                ai_mtime = _file_mtime(ai_path)
                ai_hash = _hash_file(ai_path)

            # Ensure scoring runs if ranked outputs missing or stale vs AI file
            for profile in profiles:
                ranked_json = _provider_ranked_jobs_json("openai", profile)
                ranked_csv = _provider_ranked_jobs_csv("openai", profile)
                ranked_families = _provider_ranked_families_json("openai", profile)
                shortlist_md = _provider_shortlist_md("openai", profile)
                top_md = _provider_top_md("openai", profile)

                scoring_input_selection_by_profile[profile] = _score_input_selection_detail(args)
                score_in, score_err = _resolve_score_input_path(args)
                scoring_inputs_by_profile[profile] = (
                    _file_metadata(score_in)
                    if score_in
                    else {
                        "path": None,
                        "mtime_iso": None,
                        "sha256": None,
                    }
                )

                failed_stage = f"score:{profile}"
                if score_err or score_in is None:
                    logger.error(score_err or "Unknown scoring input error")
                    _finalize("error", {"error": score_err or "score input missing", "failed_stage": failed_stage})
                    return 2

                run_dir = RUN_METADATA_DIR / _sanitize_run_id(run_id)
                archived_inputs_by_provider_profile.setdefault("openai", {})[profile] = _archive_run_inputs(
                    run_dir,
                    "openai",
                    profile,
                    score_in,
                    REPO_ROOT / "config" / "profiles.json",
                )

                need_score = not ranked_json.exists()
                if ai_mtime is not None:
                    need_score = need_score or ((_file_mtime(ranked_json) or 0) < ai_mtime)
                else:
                    need_score = True

                if need_score:
                    current_stage = f"score:{profile}"

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
                    "--min_score",
                    str(args.min_score),
                    "--out_md_top_n",
                    str(top_md),
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

        def _stage_label(base: str, provider: Optional[str] = None, profile: Optional[str] = None) -> str:
            if openai_only and (provider is None or provider == "openai"):
                if profile:
                    return f"{base}:{profile}"
                return base
            parts = [base]
            if provider:
                parts.append(provider)
            if profile:
                parts.append(profile)
            return ":".join(parts)

        def _profile_label(provider: str, profile: str) -> str:
            if openai_only and provider == "openai":
                return profile
            return f"{provider}:{profile}"

        # 1) Run pipeline stages ONCE (scrape supports multi-provider).
        current_stage = _stage_label("scrape")
        force_mode = (os.environ.get("JOBINTEL_SCRAPE_MODE") or os.environ.get("CAREERS_MODE") or "").strip()
        if args.offline:
            scrape_mode = "SNAPSHOT"
        elif force_mode:
            scrape_mode = force_mode.upper()
        else:
            scrape_mode = "AUTO"
        scrape_cmd = [
            sys.executable,
            str(REPO_ROOT / "scripts" / "run_scrape.py"),
            "--mode",
            scrape_mode,
            "--providers",
            ",".join(providers),
            "--providers-config",
            args.providers_config,
        ]
        if scrape_mode in {"LIVE", "AUTO"} and not args.snapshot_only:
            env_snapshot_dir = os.environ.get("JOBINTEL_SNAPSHOT_WRITE_DIR")
            default_snapshot_dir = env_snapshot_dir or "/tmp/jobintel_snapshots"
            snapshot_write_dir = Path(default_snapshot_dir)
            if env_snapshot_dir is None:
                try:
                    snapshot_write_dir.mkdir(parents=True, exist_ok=True)
                except OSError as exc:
                    fallback = Path(tempfile.mkdtemp(prefix="jobintel_snapshots_"))
                    logger.warning(
                        "snapshot_write_dir mkdir failed (%s); falling back to %s",
                        exc,
                        fallback,
                    )
                    snapshot_write_dir = fallback
            else:
                snapshot_write_dir.mkdir(parents=True, exist_ok=True)
            scrape_cmd += ["--snapshot-write-dir", str(snapshot_write_dir)]
        if args.snapshot_only:
            scrape_cmd.append("--snapshot-only")
        record_stage(current_stage, lambda cmd=scrape_cmd: _run(cmd, stage=current_stage))
        provenance_by_provider = _load_scrape_provenance(providers)
        all_unavailable = _all_providers_unavailable(provenance_by_provider, providers)
        if all_unavailable:
            logger.warning("All providers unavailable; suppressing Discord alerts.")

        thresholds = _provider_policy_thresholds()

        if args.scrape_only:
            for provider in providers:
                meta = provenance_by_provider.get(provider, {})
                failed, reason, line = _evaluate_provider_policy(
                    provider,
                    meta,
                    enriched_path=None,
                    thresholds=thresholds,
                    no_enrich=True,
                )
                provider_policy_lines[provider] = line
                if failed:
                    err_msg = f"Provider policy failed ({provider}): {reason}"
                    logger.error(err_msg)
                    _post_failure(webhook, stage="provider_policy", error=err_msg, no_post=args.no_post)
                    _finalize("error", {"error": err_msg, "failed_stage": "provider_policy"})
                    return 3
            logger.info("Stopping after scrape (--scrape_only set)")
            _finalize("success")
            return 0

        # 2) Run classify/enrich/AI per provider.
        for provider in providers:
            raw_path = _provider_raw_jobs_json(provider)
            labeled_path = _provider_labeled_jobs_json(provider)
            enriched_path = _provider_enriched_jobs_json(provider)
            ai_out_path = _provider_ai_jobs_json(provider)

            current_stage = _stage_label("classify", provider)
            record_stage(
                current_stage,
                lambda p=raw_path, o=labeled_path: _run(
                    [
                        sys.executable,
                        str(REPO_ROOT / "scripts" / "run_classify.py"),
                        "--in_path",
                        str(p),
                        "--out_path",
                        str(o),
                    ],
                    stage=current_stage,
                ),
            )

            current_stage = _stage_label("enrich", provider)
            if args.no_enrich:
                logger.info("Skipping enrichment step (--no_enrich set) [%s]", provider)
            else:
                record_stage(
                    current_stage,
                    lambda p=labeled_path, o=enriched_path: _run(
                        [
                            sys.executable,
                            str(REPO_ROOT / "scripts" / "run_enrich.py"),
                            "--in_path",
                            str(p),
                            "--out_path",
                            str(o),
                        ],
                        stage=current_stage,
                    ),
                )

            meta = provenance_by_provider.get(provider, {})
            failed, reason, line = _evaluate_provider_policy(
                provider,
                meta,
                enriched_path=enriched_path,
                thresholds=thresholds,
                no_enrich=args.no_enrich,
            )
            provider_policy_lines[provider] = line
            if failed:
                err_msg = f"Provider policy failed ({provider}): {reason}"
                logger.error(err_msg)
                _post_failure(
                    webhook, stage=_stage_label("provider_policy", provider), error=err_msg, no_post=args.no_post
                )
                _finalize("error", {"error": err_msg, "failed_stage": _stage_label("provider_policy", provider)})
                return 3

            # Optional AI augment stage
            if args.ai:
                current_stage = _stage_label("ai_augment", provider)
                telemetry["ai_ran"] = True
                record_stage(
                    current_stage,
                    lambda p=enriched_path, o=ai_out_path: _run(
                        [
                            sys.executable,
                            str(REPO_ROOT / "scripts" / "run_ai_augment.py"),
                            "--in_path",
                            str(p),
                            "--out_path",
                            str(o),
                        ],
                        stage=current_stage,
                    ),
                )
            # ai_only still proceeds to scoring; we skip the old early-return so scoring can run with AI outputs.

            unavailable_summary = _unavailable_summary_for(provider)

            # 3–5) For each profile: score -> diff -> state -> optional alert
            for profile in profiles:
                ranked_json = _provider_ranked_jobs_json(provider, profile)
                ranked_csv = _provider_ranked_jobs_csv(provider, profile)
                ranked_families = _provider_ranked_families_json(provider, profile)
                shortlist_md = _provider_shortlist_md(provider, profile)
                top_md = _provider_top_md(provider, profile)

                if openai_only and provider == "openai":
                    selection = _score_input_selection_detail(args)
                    in_path, score_err = _resolve_score_input_path(args)
                else:
                    selection = _score_input_selection_detail_for(args, provider)
                    in_path, score_err = _resolve_score_input_path_for(args, provider)
                scoring_input_selection_by_provider.setdefault(provider, {})[profile] = selection
                scoring_inputs_by_provider.setdefault(provider, {})[profile] = (
                    _file_metadata(in_path) if in_path else {"path": None, "mtime_iso": None, "sha256": None}
                )

                if provider == "openai":
                    scoring_input_selection_by_profile[profile] = selection
                    scoring_inputs_by_profile[profile] = (
                        _file_metadata(in_path) if in_path else {"path": None, "mtime_iso": None, "sha256": None}
                    )

                # Validate scoring prerequisites
                if score_err or in_path is None:
                    logger.error(score_err or "Unknown scoring input error")
                    failed_stage = _stage_label("score", provider, profile)
                    _finalize("error", {"error": score_err or "score input missing", "failed_stage": failed_stage})
                    return 2

                run_dir = RUN_METADATA_DIR / _sanitize_run_id(run_id)
                archived_inputs_by_provider_profile.setdefault(provider, {})[profile] = _archive_run_inputs(
                    run_dir,
                    provider,
                    profile,
                    in_path,
                    REPO_ROOT / "config" / "profiles.json",
                )

                current_stage = _stage_label("score", provider, profile)
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
                    "--min_score",
                    str(args.min_score),
                    "--out_md_top_n",
                    str(top_md),
                ] + us_only_flag
                if args.ai or args.ai_only:
                    cmd.append("--prefer_ai")

                record_stage(current_stage, lambda cmd=cmd: _run(cmd, stage=current_stage))
                _apply_score_fallback_metadata(selection, ranked_json)

                # Warn if freshly produced artifacts are not writable for future runs.
                warn_context = _stage_label("after_score", provider, profile)
                _warn_if_not_user_writable(
                    [
                        ranked_json,
                        ranked_csv,
                        ranked_families,
                        shortlist_md,
                        top_md,
                        _state_last_ranked(provider, profile),
                    ],
                    context=warn_context,
                )

                state_path = _state_last_ranked(provider, profile)
                state_exists = state_path.exists()
                curr = _read_json(ranked_json)
                alerts_json, alerts_md = _alerts_paths(provider, profile)
                last_seen_path = _last_seen_path(provider, profile)
                prev_last_seen = load_last_seen(last_seen_path)
                alerts = compute_alerts(curr, prev_last_seen, score_delta=resolve_score_delta())
                write_alerts(alerts_json, alerts_md, alerts, provider, profile)
                write_last_seen(last_seen_path, build_last_seen(curr))
                fallback_applied = selection.get("us_only_fallback", {}).get("fallback_applied") is True
                if fallback_applied:
                    label = _profile_label(provider, profile)
                    diff_counts = {
                        "new": 0,
                        "changed": 0,
                        "removed": 0,
                        "suppressed": True,
                        "reason": "us_only_fallback",
                        "note": (
                            "US-only filter removed all jobs under --no_enrich; changelog suppressed to avoid noise."
                        ),
                    }
                    diff_counts_by_provider.setdefault(provider, {})[profile] = diff_counts
                    if provider == "openai":
                        diff_counts_by_profile[profile] = diff_counts
                    logger.info("Changelog (%s) suppressed due to US-only fallback.", label)
                    _write_json(state_path, curr)
                    extra_lines: List[str] = []
                    policy_line = provider_policy_lines.get(provider)
                    if policy_line:
                        extra_lines.append(policy_line)
                    unavailable_line = _provider_unavailable_line(provider, provenance_by_provider.get(provider, {}))
                    if unavailable_line:
                        extra_lines.append(unavailable_line)
                    discord_status = _maybe_post_run_summary(
                        provider,
                        profile,
                        ranked_json,
                        diff_counts,
                        args.min_score,
                        notify_mode=notify_mode,
                        no_post=args.no_post or all_unavailable,
                        extra_lines=extra_lines or None,
                    )
                    discord_status_by_provider.setdefault(provider, {})[profile] = discord_status
                    if unavailable_summary:
                        logger.info("Unavailable reasons: %s", unavailable_summary)
                    logger.info(
                        "Done (%s). Ranked outputs:\n - %s\n - %s\n - %s",
                        label,
                        ranked_json,
                        ranked_csv,
                        shortlist_md,
                    )
                    continue

                prev: List[Dict[str, Any]] = []
                baseline_exists = False
                local_ranked = _resolve_local_last_success_ranked(provider, profile, run_id)
                if local_ranked:
                    prev = _read_json(local_ranked)
                    baseline_exists = True
                elif state_exists:
                    prev = _read_json(state_path)
                    baseline_exists = True
                else:
                    latest_ranked = _resolve_latest_run_ranked(provider, profile, run_id)
                    if latest_ranked:
                        prev = _read_json(latest_ranked)
                        baseline_exists = True

                if not baseline_exists and s3_enabled():
                    bucket = os.environ.get("JOBINTEL_S3_BUCKET", "").strip()
                    prefix = os.environ.get("JOBINTEL_S3_PREFIX", "jobintel").strip("/")
                    if bucket:
                        s3_info = _resolve_s3_baseline(provider, profile, run_id, bucket=bucket, prefix=prefix)
                        if s3_info.ranked_path and s3_info.ranked_path.exists():
                            prev = _read_json(s3_info.ranked_path)
                            baseline_exists = True
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

                diff_json_path, diff_md_path = _provider_diff_paths(provider, profile)
                diff_report = build_diff_report(
                    prev,
                    curr,
                    provider=provider,
                    profile=profile,
                    baseline_exists=baseline_exists,
                )
                _write_canonical_json(diff_json_path, diff_report)
                diff_md_path.write_text(build_diff_markdown(diff_report), encoding="utf-8")
                diff_summary_by_provider_profile.setdefault(provider, {})[profile] = _diff_summary_entry(
                    run_id=run_id,
                    provider=provider,
                    profile=profile,
                    diff_report=diff_report,
                )

                label = _profile_label(provider, profile)
                logger.info(
                    "Changelog (%s): new=%d changed=%d removed=%d",
                    label,
                    len(new_jobs),
                    len(changed_jobs),
                    len(removed_jobs),
                )
                diff_counts = {
                    "new": len(new_jobs),
                    "changed": len(changed_jobs),
                    "removed": len(removed_jobs),
                }
                if not baseline_exists:
                    diff_counts["first_run"] = True
                diff_counts_by_provider.setdefault(provider, {})[profile] = diff_counts
                if provider == "openai":
                    diff_counts_by_profile[profile] = diff_counts

                if provider in providers and os.environ.get("AI_ENABLED", "0").strip() == "1":
                    current_stage = _stage_label("ai_insights", provider, profile)
                    prev_path_arg = str(state_path) if state_exists else ""
                    cmd = [
                        sys.executable,
                        str(REPO_ROOT / "scripts" / "run_ai_insights.py"),
                        "--provider",
                        provider,
                        "--profile",
                        profile,
                        "--ranked_path",
                        str(ranked_json),
                        "--run_id",
                        run_id,
                    ]
                    if prev_path_arg:
                        cmd.extend(["--prev_path", prev_path_arg])
                    record_stage(current_stage, lambda cmd=cmd: _run(cmd, stage=current_stage))

                if (
                    provider in providers
                    and os.environ.get("AI_ENABLED", "0").strip() == "1"
                    and os.environ.get("AI_JOB_BRIEFS_ENABLED", "0").strip() == "1"
                ):
                    current_stage = _stage_label("ai_job_briefs", provider, profile)
                    cmd = [
                        sys.executable,
                        str(REPO_ROOT / "scripts" / "run_ai_job_briefs.py"),
                        "--provider",
                        provider,
                        "--profile",
                        profile,
                        "--ranked_path",
                        str(ranked_json),
                        "--run_id",
                        run_id,
                        "--max_jobs",
                        os.environ.get("AI_JOB_BRIEFS_MAX_JOBS", "10"),
                        "--max_tokens_per_job",
                        os.environ.get("AI_JOB_BRIEFS_MAX_TOKENS", "400"),
                        "--total_budget",
                        os.environ.get("AI_JOB_BRIEFS_TOTAL_BUDGET", "2000"),
                    ]
                    record_stage(current_stage, lambda cmd=cmd: _run(cmd, stage=current_stage))

                _write_json(state_path, curr)
                extra_lines: List[str] = []
                policy_line = provider_policy_lines.get(provider)
                if policy_line:
                    extra_lines.append(policy_line)
                briefs_line = _briefs_status_line(run_id, profile)
                if briefs_line:
                    extra_lines.append(briefs_line)
                unavailable_line = _provider_unavailable_line(provider, provenance_by_provider.get(provider, {}))
                if unavailable_line:
                    extra_lines.append(unavailable_line)
                discord_status = _maybe_post_run_summary(
                    provider,
                    profile,
                    ranked_json,
                    diff_counts,
                    args.min_score,
                    notify_mode=notify_mode,
                    no_post=args.no_post or all_unavailable,
                    extra_lines=extra_lines or None,
                )
                discord_status_by_provider.setdefault(provider, {})[profile] = discord_status

                interesting_new = [j for j in new_jobs if j.get("score", 0) >= args.min_alert_score]
                interesting_changed = [j for j in changed_jobs if j.get("score", 0) >= args.min_alert_score]

                if not webhook:
                    logger.info(
                        "ℹ️ No alerts (%s) (new=%d, changed=%d; webhook=unset).",
                        label,
                        len(new_jobs),
                        len(changed_jobs),
                    )
                    if unavailable_summary:
                        logger.info("Unavailable reasons: %s", unavailable_summary)
                    logger.info(
                        "Done (%s). Ranked outputs:\n - %s\n - %s\n - %s",
                        label,
                        ranked_json,
                        ranked_csv,
                        shortlist_md,
                    )
                    continue

                if not (interesting_new or interesting_changed):
                    logger.info(
                        "ℹ️ No alerts (%s) (new=%d, changed=%d; webhook=set).",
                        label,
                        len(new_jobs),
                        len(changed_jobs),
                    )
                    if unavailable_summary:
                        logger.info("Unavailable reasons: %s", unavailable_summary)
                    logger.info(
                        "Done (%s). Ranked outputs:\n - %s\n - %s\n - %s",
                        label,
                        ranked_json,
                        ranked_csv,
                        shortlist_md,
                    )
                    continue

                lines = [f"**Job alerts ({label})** — {_utcnow_iso()}"]
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

                if not _should_notify(diff_counts, notify_mode):
                    logger.info("Discord alerts skipped (mode=%s, no diffs).", notify_mode)
                elif all_unavailable:
                    logger.info("All providers unavailable; suppressing alerts.")
                else:
                    _dispatch_alerts(
                        label,
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
                    logger.info("Unavailable reasons: %s", unavailable_summary)
                logger.info(
                    "Done (%s). Ranked outputs:\n - %s\n - %s\n - %s",
                    label,
                    ranked_json,
                    ranked_csv,
                    shortlist_md,
                )

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
        logger.error(f"Stage '{current_stage}' raised SystemExit({exit_code}): {err_msg}")
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
