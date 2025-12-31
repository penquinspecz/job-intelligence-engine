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

from _bootstrap import ensure_src_on_path
ensure_src_on_path()

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple
import urllib.request
import urllib.error

from ji_engine.utils.dotenv import load_dotenv

load_dotenv()  # loads .env if present; won't override exported env vars

STATE_DIR = Path("data/state")
STATE_DIR.mkdir(parents=True, exist_ok=True)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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


def _post_discord(webhook_url: str, message: str) -> None:
    if not webhook_url or "discord.com/api/webhooks/" not in webhook_url:
        raise SystemExit("DISCORD_WEBHOOK_URL missing or doesn't look like a Discord webhook URL.")

    payload = {"content": message}
    data = json.dumps(payload).encode("utf-8")

    req = urllib.request.Request(
        webhook_url,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            # A realistic UA helps avoid some edge/WAF false positives
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X) job-intelligence-engine/1.0",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            resp.read()
            return
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print("Discord webhook POST failed:", e.code)
        print(body[:2000])
        raise


def _resolve_profiles(args: argparse.Namespace) -> List[str]:
    """
    Backward-compatible:
      - If --profiles is provided (default "cs"), run those.
      - Else fall back to --profile.

    We keep --profile because you already use it and it's convenient.
    """
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

    # Keep existing single-profile flag
    ap.add_argument("--profile", default="cs", help="Scoring profile name (cs|tam|se)")

    # Add multi-profile runner (comma-separated)
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

    # Test post mode
    if args.test_post:
        webhook = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
        if not webhook:
            raise SystemExit("DISCORD_WEBHOOK_URL not set (check .env and export).")
        _post_discord(webhook, "test_post ✅ (run_daily)")
        print("✅ test_post sent")
        return 0

    profiles = _resolve_profiles(args)
    us_only_flag = ["--us_only"] if args.us_only else []

    # 1) Run pipeline stages ONCE
    _run([sys.executable, "scripts/run_scrape.py"])
    _run([sys.executable, "scripts/run_classify.py"])
    _run([sys.executable, "-m", "scripts.enrich_jobs"])

    # 2–5) For each profile: score -> diff -> state -> optional alert
    webhook = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()

    for profile in profiles:
        ranked_json = Path(f"data/openai_ranked_jobs.{profile}.json")
        ranked_csv = Path(f"data/openai_ranked_jobs.{profile}.csv")
        shortlist_md = Path(f"data/openai_shortlist.{profile}.md")

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

        state_path = STATE_DIR / f"last_ranked.{profile}.json"
        curr = _read_json(ranked_json)
        prev = _read_json(state_path) if state_path.exists() else []
        new_jobs, changed_jobs = _diff(prev, curr)

        _write_json(state_path, curr)

        interesting_new = [j for j in new_jobs if j.get("score", 0) >= args.min_alert_score]
        interesting_changed = [j for j in changed_jobs if j.get("score", 0) >= args.min_alert_score]

        if not webhook:
            print(f"ℹ️ No alerts ({profile}) (new={len(new_jobs)}, changed={len(changed_jobs)}; webhook=unset).")
            print(f"Done ({profile}). Ranked outputs:\n - {ranked_json}\n - {ranked_csv}\n - {shortlist_md}")
            continue

        if not (interesting_new or interesting_changed):
            print(f"ℹ️ No alerts ({profile}) (new={len(new_jobs)}, changed={len(changed_jobs)}; webhook=set).")
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
            _post_discord(webhook, msg)
            print(f"✅ Discord alert sent ({profile}).")

        print(f"Done ({profile}). Ranked outputs:\n - {ranked_json}\n - {ranked_csv}\n - {shortlist_md}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
