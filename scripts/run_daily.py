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
from ji_engine.config import (
    STATE_DIR,
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
        finally:
            sys.argv = old_argv
    else:
        script_path = argv[0]
        args = argv[1:]
        old_argv = sys.argv
        sys.argv = [script_path, *args]
        try:
            runpy.run_path(script_path, run_name="__main__")
        finally:
            sys.argv = old_argv


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def _hash_file(path: Path) -> Optional[str]:
    if not path.exists():
        return None
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except Exception:
        return None


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
    apply_url = (job.get("apply_url") or "").strip()
    if apply_url:
        return apply_url
    return f"{job.get('title','')}|{job.get('location') or job.get('locationName') or ''}"


def _hash_job(job: Dict[str, Any]) -> str:
    payload = {
        "title": job.get("title"),
        "location": job.get("location") or job.get("locationName"),
        "role_band": job.get("role_band"),
        "score": job.get("score"),
        "base_score": job.get("base_score"),
        "profile_delta": job.get("profile_delta"),
        "enrich_status": job.get("enrich_status"),
        "enrich_reason": job.get("enrich_reason"),
        "jd_text_chars": job.get("jd_text_chars"),
        "apply_url": job.get("apply_url"),
    }
    raw = json.dumps(payload, sort_keys=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _diff(
    prev: List[Dict[str, Any]],
    curr: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    prev_map = {_job_key(j): (j, _hash_job(j)) for j in prev}
    curr_map = {_job_key(j): (j, _hash_job(j)) for j in curr}

    new_jobs: List[Dict[str, Any]] = []
    changed_jobs: List[Dict[str, Any]] = []

    for k, (cj, ch) in curr_map.items():
        if k not in prev_map:
            new_jobs.append(cj)
        else:
            _, ph = prev_map[k]
            if ph != ch:
                changed_jobs.append(cj)

    new_jobs.sort(key=lambda x: x.get("score", 0), reverse=True)
    changed_jobs.sort(key=lambda x: x.get("score", 0), reverse=True)
    return new_jobs, changed_jobs


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
    ap.add_argument(
        "--no_subprocess",
        action="store_true",
        help="Run stages in-process (library mode). Default uses subprocesses.",
    )
    ap.add_argument("--log_json", action="store_true", help="Emit JSON logs for aggregation systems")

    args = ap.parse_args()
    global USE_SUBPROCESS
    USE_SUBPROCESS = not args.no_subprocess
    _setup_logging(args.log_json)
    webhook = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()

    if args.test_post:
        if not webhook:
            raise SystemExit("DISCORD_WEBHOOK_URL not set (check .env and export).")
        ok = _post_discord(webhook, "test_post ✅ (run_daily)")
        logger.info("✅ test_post sent" if ok else "⚠️ test_post failed")
        return 0

    _acquire_lock(timeout_sec=0)
    logger.info(f"===== jobintel start {_utcnow_iso()} pid={os.getpid()} =====")

    telemetry: Dict[str, Any] = {
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
        if extra:
            telemetry.update(extra)
        _write_last_run(telemetry)

    current_stage = "startup"

    def record_stage(name: str, fn) -> Any:
        t0 = time.time()
        result = fn()
        telemetry["stages"][name] = {"duration_sec": round(time.time() - t0, 3)}
        return result

    try:
        profiles = _resolve_profiles(args)
        us_only_flag = ["--us_only"] if args.us_only else []
        ai_required = args.ai

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
            # No-AI short-circuit: safe to skip everything downstream.
            if not ai_required:
                telemetry["hashes"] = curr_hashes
                telemetry["counts"] = {
                    "raw": _safe_len(RAW_JOBS_JSON),
                    "labeled": _safe_len(LABELED_JOBS_JSON),
                    "enriched": _safe_len(ENRICHED_JOBS_JSON),
                }
                telemetry["stages"] = {"short_circuit": {"duration_sec": 0.0}}
                _update_ai_telemetry(False)
                _finalize("short_circuit")
                logger.info("No changes detected (raw/labeled/enriched). Short-circuiting downstream stages.")
                return 0

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

                need_score = (not ranked_json.exists())
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
                        str(ai_path if ai_path.exists() else ENRICHED_JOBS_JSON),
                        "--out_json",
                        str(ranked_json),
                        "--out_csv",
                        str(ranked_csv),
                        "--out_families",
                        str(ranked_families),
                        "--out_md",
                        str(shortlist_md),
                    ] + us_only_flag
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
        current_stage = "classify"
        record_stage(current_stage, lambda: _run([sys.executable, str(REPO_ROOT / "scripts" / "run_classify.py")], stage=current_stage))
        current_stage = "enrich"
        if args.no_enrich:
            logger.info("Skipping enrichment step (--no_enrich set)")
        else:
            record_stage(current_stage, lambda: _run([sys.executable, "-m", "scripts.enrich_jobs"], stage=current_stage))

        # Optional AI augment stage
        if args.ai:
            current_stage = "ai_augment"
            telemetry["ai_ran"] = True
            record_stage(current_stage, lambda: _run([sys.executable, str(REPO_ROOT / "scripts" / "run_ai_augment.py")], stage=current_stage))

        if args.ai_only:
            _finalize("success")
            return 0

        unavailable_summary = _unavailable_summary()

        # 2–5) For each profile: score -> diff -> state -> optional alert
        for profile in profiles:
            ranked_json = ranked_jobs_json(profile)
            ranked_csv = ranked_jobs_csv(profile)
            ranked_families = ranked_families_json(profile)
            shortlist_md = shortlist_md_path(profile)
            # Prefer AI-enriched input if present
            enriched_ai = ENRICHED_JOBS_JSON.with_name("openai_enriched_jobs_ai.json")
            in_path = enriched_ai if enriched_ai.exists() else ENRICHED_JOBS_JSON

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

            record_stage(current_stage, lambda cmd=cmd: _run(cmd, stage=current_stage))

            state_path = state_last_ranked(profile)
            curr = _read_json(ranked_json)
            prev = _read_json(state_path) if state_path.exists() else []
            new_jobs, changed_jobs = _diff(prev, curr)

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

            msg = "\n".join(lines)
            if args.no_post:
                logger.info(f"Skipping Discord post (--no_post). Message for {profile} would have been:\n")
                logger.info(msg)
            else:
                if unavailable_summary:
                    lines.append(f"Unavailable reasons: {unavailable_summary}")
                ok = _post_discord(webhook, msg)
                logger.info(
                    f"✅ Discord alert sent ({profile})." if ok else "⚠️ Discord alert NOT sent (pipeline still completed)."
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
        return 1
    except Exception as e:
        logger.error(f"Stage '{current_stage}' failed unexpectedly: {e!r}")
        _post_failure(
            webhook,
            stage=current_stage or "unexpected",
            error=repr(e),
            no_post=args.no_post,
        )
        _finalize("error", {"error": repr(e), "failed_stage": current_stage})
        return 1
    finally:
        logger.info(f"===== jobintel end {_utcnow_iso()} =====")


if __name__ == "__main__":
    raise SystemExit(main())