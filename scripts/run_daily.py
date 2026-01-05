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
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple
import urllib.error
import urllib.request

from ji_engine.utils.dotenv import load_dotenv
from ji_engine.config import (
    STATE_DIR,
    LOCK_PATH,
    ranked_jobs_json,
    ranked_jobs_csv,
    shortlist_md as shortlist_md_path,
    state_last_ranked,
)

load_dotenv()  # loads .env if present; won't override exported env vars
STATE_DIR.mkdir(parents=True, exist_ok=True)


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
                print(f"⚠️ Stale lock detected (pid={existing_pid}). Removing {LOCK_PATH}.")
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


def _run(cmd: List[str]) -> None:
    print("\n$ " + " ".join(cmd))
    subprocess.run(cmd, check=True)


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


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
        print("⚠️ DISCORD_WEBHOOK_URL missing or doesn't look like a Discord webhook URL. Skipping post.")
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
        print(f"Discord webhook POST failed: {e.code}")
        print(body[:2000])
        if e.code == 404 and "10015" in body:
            print("⚠️ Discord says: Unknown Webhook (rotated/deleted/wrong URL). Update DISCORD_WEBHOOK_URL in .env.")
        return False
    except Exception as e:
        print(f"Discord webhook POST failed: {e!r}")
        return False


def _post_failure(webhook_url: str, stage: str, error: str) -> None:
    """Best-effort failure notification. Never raises."""
    if not webhook_url:
        return

    msg = (
        "**🚨 Job Pipeline FAILED**\n"
        f"Stage: `{stage}`\n"
        f"Time: `{_utcnow_iso()}`\n"
        f"Error:\n```{error[-1800:]}```"
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

    args = ap.parse_args()
    webhook = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()

    if args.test_post:
        if not webhook:
            raise SystemExit("DISCORD_WEBHOOK_URL not set (check .env and export).")
        ok = _post_discord(webhook, "test_post ✅ (run_daily)")
        print("✅ test_post sent" if ok else "⚠️ test_post failed")
        return 0

    _acquire_lock(timeout_sec=0)
    print(f"===== jobintel start {_utcnow_iso()} pid={os.getpid()} =====")

    try:
        profiles = _resolve_profiles(args)
        us_only_flag = ["--us_only"] if args.us_only else []

        # 1) Run pipeline stages ONCE
        _run([sys.executable, "scripts/run_scrape.py", "--mode", "AUTO"])
        _run([sys.executable, "scripts/run_classify.py"])
        _run([sys.executable, "-m", "scripts.enrich_jobs"])

        # 2–5) For each profile: score -> diff -> state -> optional alert
        for profile in profiles:
            ranked_json = ranked_jobs_json(profile)
            ranked_csv = ranked_jobs_csv(profile)
            shortlist_md = shortlist_md_path(profile)

            cmd = [
                sys.executable,
                "scripts/score_jobs.py",
                "--profile",
                profile,
                "--out_json",
                str(ranked_json),
                "--out_csv",
                str(ranked_csv),
                "--out_md",
                str(shortlist_md),
            ] + us_only_flag

            _run(cmd)

            state_path = state_last_ranked(profile)
            curr = _read_json(ranked_json)
            prev = _read_json(state_path) if state_path.exists() else []
            new_jobs, changed_jobs = _diff(prev, curr)

            _write_json(state_path, curr)

            interesting_new = [j for j in new_jobs if j.get("score", 0) >= args.min_alert_score]
            interesting_changed = [j for j in changed_jobs if j.get("score", 0) >= args.min_alert_score]

            if not webhook:
                print(
                    f"ℹ️ No alerts ({profile}) (new={len(new_jobs)}, changed={len(changed_jobs)}; webhook=unset)."
                )
                print(f"Done ({profile}). Ranked outputs:\n - {ranked_json}\n - {ranked_csv}\n - {shortlist_md}")
                continue

            if not (interesting_new or interesting_changed):
                print(
                    f"ℹ️ No alerts ({profile}) (new={len(new_jobs)}, changed={len(changed_jobs)}; webhook=set)."
                )
                print(f"Done ({profile}). Ranked outputs:\n - {ranked_json}\n - {ranked_csv}\n - {shortlist_md}")
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
                print(f"Skipping Discord post (--no_post). Message for {profile} would have been:\n")
                print(msg)
            else:
                ok = _post_discord(webhook, msg)
                print(f"✅ Discord alert sent ({profile})." if ok else "⚠️ Discord alert NOT sent (pipeline still completed).")

            print(f"Done ({profile}). Ranked outputs:\n - {ranked_json}\n - {ranked_csv}\n - {shortlist_md}")

        return 0

    except subprocess.CalledProcessError as e:
        cmd_str = " ".join(e.cmd) if isinstance(e.cmd, (list, tuple)) else str(e.cmd)
        _post_failure(webhook, stage="subprocess", error=f"{e}\ncmd={cmd_str}")
        return 1
    except Exception as e:
        _post_failure(webhook, stage="unexpected", error=repr(e))
        return 1
    finally:
        print(f"===== jobintel end {_utcnow_iso()} =====")


if __name__ == "__main__":
    raise SystemExit(main())