# Pipeline Files
Included: `scripts/run_daily.py`, `scripts/run_scrape.py`, `scripts/run_classify.py`, `scripts/enrich_jobs.py`, `scripts/score_jobs.py`

Why they matter: entrypoints for the end-to-end pipeline (orchestration, scrape, classify, enrich, score).

Omitted: none (full contents below).

## scripts/run_daily.py
```
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
    ranked_families_json,
    shortlist_md as shortlist_md_path,
    state_last_ranked,
)

logger = logging.getLogger(__name__)

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


def _run(cmd: List[str]) -> None:
    logger.info("\n$ " + " ".join(cmd))
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


def _post_failure(webhook_url: str, stage: str, error: str, no_post: bool) -> None:
    """Best-effort failure notification. Never raises."""
    if no_post or not webhook_url:
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
    if not logging.getLogger().hasHandlers():
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

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
        logger.info("✅ test_post sent" if ok else "⚠️ test_post failed")
        return 0

    _acquire_lock(timeout_sec=0)
    logger.info(f"===== jobintel start {_utcnow_iso()} pid={os.getpid()} =====")

    current_stage = "startup"

    try:
        profiles = _resolve_profiles(args)
        us_only_flag = ["--us_only"] if args.us_only else []

        # 1) Run pipeline stages ONCE
        current_stage = "scrape"
        _run([sys.executable, "scripts/run_scrape.py", "--mode", "AUTO"])
        current_stage = "classify"
        _run([sys.executable, "scripts/run_classify.py"])
        current_stage = "enrich"
        _run([sys.executable, "-m", "scripts.enrich_jobs"])

        # 2–5) For each profile: score -> diff -> state -> optional alert
        for profile in profiles:
            ranked_json = ranked_jobs_json(profile)
            ranked_csv = ranked_jobs_csv(profile)
            ranked_families = ranked_families_json(profile)
            shortlist_md = shortlist_md_path(profile)

            current_stage = f"score:{profile}"
            cmd = [
                sys.executable,
                "scripts/score_jobs.py",
                "--profile",
                profile,
                "--out_json",
                str(ranked_json),
                "--out_csv",
                str(ranked_csv),
                "--out_families",
                str(ranked_families),
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
                logger.info(
                    f"ℹ️ No alerts ({profile}) (new={len(new_jobs)}, changed={len(changed_jobs)}; webhook=unset)."
                )
                logger.info(f"Done ({profile}). Ranked outputs:\n - {ranked_json}\n - {ranked_csv}\n - {shortlist_md}")
                continue

            if not (interesting_new or interesting_changed):
                logger.info(
                    f"ℹ️ No alerts ({profile}) (new={len(new_jobs)}, changed={len(changed_jobs)}; webhook=set)."
                )
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
                ok = _post_discord(webhook, msg)
                logger.info(
                    f"✅ Discord alert sent ({profile})." if ok else "⚠️ Discord alert NOT sent (pipeline still completed)."
                )

            logger.info(f"Done ({profile}). Ranked outputs:\n - {ranked_json}\n - {ranked_csv}\n - {shortlist_md}")

        return 0

    except subprocess.CalledProcessError as e:
        cmd_str = " ".join(e.cmd) if isinstance(e.cmd, (list, tuple)) else str(e.cmd)
        _post_failure(webhook, stage=current_stage, error=f"{e}\ncmd={cmd_str}", no_post=args.no_post)
        return 1
    except Exception as e:
        _post_failure(webhook, stage=current_stage or "unexpected", error=repr(e), no_post=args.no_post)
        return 1
    finally:
        logger.info(f"===== jobintel end {_utcnow_iso()} =====")


if __name__ == "__main__":
    raise SystemExit(main())
```

## scripts/run_scrape.py
```
#!/usr/bin/env python3
from __future__ import annotations

import argparse
import logging
import os

from ji_engine.config import DATA_DIR
from ji_engine.scraper import ScraperManager

logger = logging.getLogger(__name__)


def main() -> int:
    if not logging.getLogger().hasHandlers():
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--mode",
        choices=["SNAPSHOT", "LIVE", "AUTO"],
        default=os.getenv("CAREERS_MODE", "AUTO"),
        help="Scrape mode. Default from CAREERS_MODE env var.",
    )
    args = ap.parse_args()

    # Centralized path (no stringly-typed "data")
    manager = ScraperManager(output_dir=str(DATA_DIR))

    if args.mode == "SNAPSHOT":
        logger.info("manager.run_all(mode=SNAPSHOT)")
        manager.run_all(mode="SNAPSHOT")
        return 0

    if args.mode == "LIVE":
        logger.info("manager.run_all(mode=LIVE)")
        manager.run_all(mode="LIVE")
        return 0

    # AUTO: try LIVE, fall back to SNAPSHOT
    try:
        logger.info("manager.run_all(mode=LIVE)")
        manager.run_all(mode="LIVE")
    except Exception as e:
        logger.warning(f"[run_scrape] LIVE failed ({e!r}) → falling back to SNAPSHOT")
        logger.info("manager.run_all(mode=SNAPSHOT)")
        manager.run_all(mode="SNAPSHOT")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

## scripts/run_classify.py
```
#!/usr/bin/env python3
"""
Entry point to run the job classification pipeline.

Usage (from repo root, with venv active):
  python scripts/run_classify.py
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import List

from ji_engine.config import LABELED_JOBS_JSON, RAW_JOBS_JSON
from ji_engine.models import JobSource, RawJobPosting
from ji_engine.profile_loader import load_candidate_profile
from ji_engine.pipeline.classifier import label_jobs

logger = logging.getLogger(__name__)


def _load_raw_jobs(path: Path) -> List[RawJobPosting]:
    if not path.exists():
        raise FileNotFoundError(f"Jobs file not found: {path}")

    jobs: List[RawJobPosting] = []
    data = json.loads(path.read_text(encoding="utf-8"))

    for d in data:
        # Normalize types for RawJobPosting(**d)
        d["source"] = JobSource(d["source"])
        d["scraped_at"] = datetime.fromisoformat(d["scraped_at"])
        jobs.append(RawJobPosting(**d))

    return jobs


def main() -> int:
    if not logging.getLogger().hasHandlers():
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    profile = load_candidate_profile()

    try:
        jobs = _load_raw_jobs(RAW_JOBS_JSON)
    except FileNotFoundError as e:
        logger.error(f"Error: {e}")
        return 1

    labeled = label_jobs(jobs, profile)

    counts = {"RELEVANT": 0, "MAYBE": 0, "IRRELEVANT": 0}
    for result in labeled:
        counts[result["relevance"]] += 1

    logger.info("\nClassification Summary:")
    logger.info(f"  RELEVANT:   {counts['RELEVANT']}")
    logger.info(f"  MAYBE:      {counts['MAYBE']}")
    logger.info(f"  IRRELEVANT: {counts['IRRELEVANT']}")
    logger.info(f"  Total:      {len(labeled)}")

    relevant_jobs = [r for r in labeled if r["relevance"] == "RELEVANT"]
    logger.info(f"\nFirst {min(10, len(relevant_jobs))} RELEVANT jobs:")
    for i, job in enumerate(relevant_jobs[:10], 1):
        logger.info(f"\n{i}. {job['title']}")
        logger.info(f"   {job['apply_url']}")

    # Write labeled jobs to JSON file
    output_data = []
    for job, labeled_result in zip(jobs, labeled):
        output_data.append(
            {
                "title": job.title,
                "apply_url": job.apply_url,
                "detail_url": job.detail_url,
                "location": job.location,
                "team": job.team,
                "relevance": labeled_result["relevance"],
            }
        )

    LABELED_JOBS_JSON.parent.mkdir(parents=True, exist_ok=True)
    LABELED_JOBS_JSON.write_text(
        json.dumps(output_data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    logger.info(f"\nWrote labeled jobs to {LABELED_JOBS_JSON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

## scripts/enrich_jobs.py
```
#!/usr/bin/env python3
"""
Enrich labeled jobs by fetching job data via Ashby GraphQL API.

Falls back to HTML base page when API returns missing/empty descriptionHtml.
If API returns jobPosting null, mark unavailable and do NOT HTML-fallback.

Usage:
  python -m scripts.enrich_jobs
  python scripts/enrich_jobs.py
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup

from ji_engine.config import ASHBY_CACHE_DIR, ENRICHED_JOBS_JSON, LABELED_JOBS_JSON
from ji_engine.integrations.ashby_graphql import fetch_job_posting
from ji_engine.integrations.html_to_text import html_to_text

logger = logging.getLogger(__name__)

DEBUG = os.getenv("JI_DEBUG") == "1"

ORG = "openai"
CACHE_DIR = ASHBY_CACHE_DIR


def _extract_job_id_from_url(url: str) -> Optional[str]:
    """
    Extract jobPostingId from apply_url using regex pattern.
    Pattern: /openai/([0-9a-f-]{36})/application
    """
    pattern = r"/openai/([0-9a-f-]{36})/application"
    match = re.search(pattern, url, re.IGNORECASE)
    return match.group(1) if match else None


def _derive_fallback_url(apply_url: str) -> str:
    """Derive base posting URL (without /application) for HTML fallback."""
    return apply_url[:-len("/application")] if apply_url.endswith("/application") else apply_url


def _fetch_html_fallback(url: str) -> Optional[str]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:146.0) "
            "Gecko/20100101 Firefox/146.0"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=20)
        resp.raise_for_status()
        html = resp.text
        html_lower = html.lower()
        if "<html" not in html_lower and "<!doctype" not in html_lower:
            return None
        return html
    except Exception as e:
        logger.info(f" ⚠️ HTML fallback fetch failed: {e}")
        return None


def _extract_jd_from_html(html: str) -> Optional[str]:
    soup = BeautifulSoup(html, "html.parser")

    selectors = [
        "div[data-testid='jobPostingDescription']",
        "main",
        "article",
    ]

    for selector in selectors:
        container = soup.select_one(selector)
        if container:
            for tag in container.find_all(["script", "style"]):
                tag.decompose()
            text = container.get_text(separator="\n", strip=True)
            if text and len(text) > 200:
                return text

    for tag in soup.find_all(["script", "style", "nav", "header", "footer"]):
        tag.decompose()
    text = soup.get_text(separator="\n", strip=True)
    return text if text and len(text) > 200 else None


def _apply_api_response(
    job: Dict[str, Any],
    api_data: Dict[str, Any] | None,
    fallback_url: str,
) -> Tuple[Dict[str, Any], bool]:
    """
    Returns (updated_job, fallback_needed)
    """
    updated = dict(job)
    updated.setdefault("enrich_status", None)
    updated.setdefault("enrich_reason", None)

    clean_title = job.get("title")
    location = job.get("location")
    team = job.get("team")
    jd_text: Optional[str] = None

    if not api_data or api_data.get("errors"):
        updated["enrich_status"] = "failed"
        updated["enrich_reason"] = "api_errors" if api_data and api_data.get("errors") else "api_fetch_failed"
        updated.update({"title": clean_title, "location": location, "team": team, "jd_text": jd_text})
        return updated, True

    jp = (api_data.get("data") or {}).get("jobPosting")
    if jp is None:
        if DEBUG:
            print(" jobPosting is null (likely unlisted/blocked/removed); marking unavailable")
            print(f" fallback_url: {fallback_url}")
        updated["enrich_status"] = "unavailable"
        updated["enrich_reason"] = "api_jobPosting_null"
        updated.update({"title": clean_title, "location": location, "team": team, "jd_text": None})
        return updated, False  # do NOT HTML-fallback

    clean_title = jp.get("title") or clean_title
    location = jp.get("locationName") or location

    team_names = jp.get("teamNames")
    if isinstance(team_names, list) and team_names:
        team_str = ", ".join([t for t in team_names if isinstance(t, str) and t.strip()])
        team = team_str if team_str else team

    description_html = (jp.get("descriptionHtml") or "").strip()
    if description_html:
        jd_text = html_to_text(description_html)
        if jd_text:
            updated["enrich_status"] = "enriched"
            updated["enrich_reason"] = None
            updated.update({"title": clean_title, "location": location, "team": team, "jd_text": jd_text})
            return updated, False
        else:
            if DEBUG:
                print(" descriptionHtml converted to empty text - falling back to HTML")
            updated["enrich_status"] = "failed"
            updated["enrich_reason"] = "description_html_empty_text"
            updated.update({"title": clean_title, "location": location, "team": team, "jd_text": None})
            return updated, True

    if DEBUG:
        logger.info(" descriptionHtml missing/empty; falling back to HTML base page")
        logger.info(f" fallback_url: {fallback_url}")
    updated["enrich_status"] = "failed"
    updated["enrich_reason"] = "description_html_missing"
    updated.update({"title": clean_title, "location": location, "team": team, "jd_text": None})
    return updated, True


def main() -> int:
    if not logging.getLogger().hasHandlers():
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    if not LABELED_JOBS_JSON.exists():
        logger.error(f"Error: Input file not found: {LABELED_JOBS_JSON}")
        return 1

    jobs = json.loads(LABELED_JOBS_JSON.read_text(encoding="utf-8"))
    enriched: List[Dict[str, Any]] = []
    stats = {"enriched": 0, "unavailable": 0, "failed": 0}

    filtered_jobs = [j for j in jobs if j.get("relevance") in ("RELEVANT", "MAYBE")]

    logger.info(f"Loaded {len(jobs)} labeled jobs")
    logger.info(f"Filtering for RELEVANT/MAYBE: {len(filtered_jobs)} jobs to enrich\n")

    for i, job in enumerate(filtered_jobs, 1):
        apply_url = job.get("apply_url", "")
        if not apply_url:
            logger.info(f" [{i}/{len(filtered_jobs)}] Skipping - no apply_url")
            enriched.append({**job, "jd_text": None, "fetched_at": None})
            continue

        logger.info(f" [{i}/{len(filtered_jobs)}] Processing: {job.get('title', 'Unknown')}")

        job_id = _extract_job_id_from_url(apply_url)
        if not job_id:
            logger.info(" ⚠️ Cannot extract jobPostingId from URL - not enrichable")
            logger.info(f" URL: {apply_url}")
            enriched.append({**job, "jd_text": None, "fetched_at": None})
            continue

        fallback_url = _derive_fallback_url(apply_url)

        try:
            api_data = fetch_job_posting(org=ORG, job_id=job_id, cache_dir=CACHE_DIR)
        except Exception as e:
            logger.info(f" ❌ API fetch failed: {e}")
            api_data = None

        updated_job, fallback_needed = _apply_api_response(job, api_data, fallback_url)
        jd_text = updated_job.get("jd_text")

        if fallback_needed:
            logger.info(" ⚠️ Falling back to HTML parsing")
            if DEBUG:
                logger.info(f" fallback_url: {fallback_url}")
            html = _fetch_html_fallback(fallback_url)
            if html:
                jd_text = _extract_jd_from_html(html)
                if jd_text:
                    logger.info(f" ✅ Extracted from HTML: {len(jd_text)} chars")
                    updated_job["jd_text"] = jd_text
                    updated_job["enrich_status"] = "enriched"
                    updated_job["enrich_reason"] = updated_job.get("enrich_reason") or "html_fallback"
                else:
                    logger.info(" ❌ HTML extraction failed")
                    updated_job["enrich_status"] = updated_job.get("enrich_status") or "failed"
                    updated_job["enrich_reason"] = updated_job.get("enrich_reason") or "html_extraction_failed"
            else:
                logger.info(" ❌ HTML fetch failed")
                updated_job["enrich_status"] = updated_job.get("enrich_status") or "failed"
                updated_job["enrich_reason"] = updated_job.get("enrich_reason") or "html_fetch_failed"

        if updated_job.get("enrich_status") == "unavailable":
            jd_text = None

        updated_job["fetched_at"] = datetime.utcnow().isoformat()

        if jd_text:
            logger.info(f" ✅ Final JD length: {len(jd_text)} chars")
            stats["enriched"] += 1
        else:
            status = updated_job.get("enrich_status")
            if status == "unavailable":
                stats["unavailable"] += 1
            else:
                stats["failed"] += 1
            logger.info(" ❌ No JD text extracted")

        enriched.append(updated_job)

    ENRICHED_JOBS_JSON.parent.mkdir(parents=True, exist_ok=True)
    ENRICHED_JOBS_JSON.write_text(
        json.dumps(enriched, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    logger.info("\n" + "=" * 60)
    logger.info("Enrichment Summary:")
    logger.info(f" Total processed: {len(enriched)}")
    logger.info(f" Enriched: {stats['enriched']}")
    logger.info(f" Unavailable: {stats['unavailable']}")
    logger.info(f" Failed: {stats['failed']}")
    logger.info(f" Output: {ENRICHED_JOBS_JSON}")
    logger.info("=" * 60)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

## scripts/score_jobs.py
```
#!/usr/bin/env python3
"""
Score enriched job postings for CS-fit / customer-facing technical roles.

Input:
  data/openai_enriched_jobs.json (produced by scripts.enrich_jobs)

Outputs:
  data/openai_ranked_jobs.json
  data/openai_ranked_jobs.csv
  data/openai_ranked_families.json
  data/openai_shortlist.md

Usage:
  python scripts/score_jobs.py
  # optional:
  python scripts/score_jobs.py --in data/openai_enriched_jobs.json \
      --out_json data/openai_ranked_jobs.json \
      --out_csv data/openai_ranked_jobs.csv \
      --out_families data/openai_ranked_families.json \
      --out_md data/openai_shortlist.md
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ji_engine.config import (
    ENRICHED_JOBS_JSON,
    LABELED_JOBS_JSON,
    ranked_families_json,
    ranked_jobs_csv,
    ranked_jobs_json,
    shortlist_md,
)

logger = logging.getLogger(__name__)

def load_profiles(path: str) -> Dict[str, Any]:
    p = Path(path)
    if not p.exists():
        raise SystemExit(f"Profiles config not found: {p}")
    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit("profiles.json must be an object mapping profile_name -> config")
    return data


def apply_profile(profile_name: str, profiles: Dict[str, Any]) -> None:
    """
    Overwrite global ROLE_BAND_MULTIPLIERS + PROFILE_WEIGHTS with selected profile settings.
    """
    if profile_name not in profiles:
        raise SystemExit(f"Unknown profile '{profile_name}'. Available: {', '.join(sorted(profiles.keys()))}")

    cfg = profiles[profile_name]
    rbm = cfg.get("role_band_multipliers")
    pw = cfg.get("profile_weights")

    if not isinstance(rbm, dict) or not isinstance(pw, dict):
        raise SystemExit(f"Profile '{profile_name}' must contain role_band_multipliers and profile_weights dicts")

    # overwrite in-place so rest of script doesn't change
    ROLE_BAND_MULTIPLIERS.clear()
    ROLE_BAND_MULTIPLIERS.update({str(k): float(v) for k, v in rbm.items()})

    PROFILE_WEIGHTS.clear()
    PROFILE_WEIGHTS.update({str(k): int(v) for k, v in pw.items()})



# ------------------------------------------------------------
# Tunables: role-band multipliers (this is your big lever)
# ------------------------------------------------------------

ROLE_BAND_MULTIPLIERS: Dict[str, float] = {
    "CS_CORE": 1.25,
    "CS_ADJACENT": 1.15,
    "SOLUTIONS": 1.05,
    "OTHER": 0.95,
}


# ------------------------------------------------------------
# Tunables: profile weights (Step 3)
# You can tweak these numbers anytime without touching logic.
# ------------------------------------------------------------

PROFILE_WEIGHTS = {
    "boost_cs_core": 15,
    "boost_cs_adjacent": 5,
    "boost_solutions": 2,
    "penalty_research_heavy": -8,
    "penalty_low_level": -5,
    "penalty_strong_swe_only": -4,
    # was 6 — increase so it outranks Partner Solutions Architect
    "pin_manager_ai_deployment": 30,
}


# ------------------------------------------------------------
# Rules for base scoring
# ------------------------------------------------------------

@dataclass(frozen=True)
class Rule:
    name: str
    pattern: re.Pattern
    weight: int
    scope: str  # "title" | "text" | "either"


def _compile_rules() -> Tuple[List[Rule], List[Rule]]:
    """
    Returns (positive_rules, negative_rules).
    Patterns are intentionally broad but phrase-ish to avoid noise.
    """
    pos = [
        Rule("customer_success", re.compile(r"\bcustomer success\b", re.I), 8, "either"),
        Rule("value_realization", re.compile(r"\bvalue realization\b|\bbusiness value\b|\bROI\b", re.I), 7, "either"),
        Rule("adoption_onboarding_enablement", re.compile(r"\badoption\b|\bonboarding\b|\benablement\b", re.I), 6, "text"),
        Rule("deployment_implementation", re.compile(r"\bdeploy(ment|ing|ed)?\b|\bimplementation\b", re.I), 5, "either"),
        Rule("stakeholder_exec", re.compile(r"\bstakeholder(s)?\b|\bexecutive\b|\bC-?level\b", re.I), 4, "text"),
        Rule("enterprise_strategic", re.compile(r"\benterprise\b|\bstrategic\b|\bkey account\b", re.I), 3, "text"),
        Rule("customer_facing", re.compile(r"\bcustomer-?facing\b|\bexternal\b clients?\b", re.I), 4, "text"),
        Rule("consultative_advisory", re.compile(r"\badvis(e|ory)\b|\bconsult(ing|ative)\b", re.I), 3, "text"),
        Rule("discovery_requirements", re.compile(r"\bdiscovery\b|\bneeds assessment\b|\brequirements gathering\b", re.I), 3, "text"),
        Rule("integrations_apis", re.compile(r"\bintegration(s)?\b|\bAPI(s)?\b|\bSDK\b", re.I), 2, "text"),
        Rule("governance_security_compliance", re.compile(r"\bgovernance\b|\bsecurity\b|\bcompliance\b", re.I), 2, "text"),
        Rule("renewal_retention_expansion", re.compile(r"\brenewal(s)?\b|\bretention\b|\bexpansion\b|\bupsell\b|\bcross-?sell\b", re.I), 3, "text"),
        # title-forward signals (but keep weights lower than CS/value/adoption)
        Rule("solutions_architect", re.compile(r"\bsolutions architect\b", re.I), 6, "title"),
        Rule("solutions_engineer", re.compile(r"\bsolutions engineer\b", re.I), 6, "title"),
        Rule("forward_deployed", re.compile(r"\bforward deployed\b", re.I), 5, "either"),
        Rule("program_manager", re.compile(r"\bprogram manager\b", re.I), 2, "title"),
    ]

    neg = [
        Rule("research_scientist", re.compile(r"\bresearch scientist\b|\bresearcher\b", re.I), -10, "either"),
        Rule("phd_required", re.compile(r"\bPhD\b|\bdoctoral\b", re.I), -8, "text"),
        Rule("model_training_pretraining", re.compile(r"\bpretraining\b|\bRLHF\b|\btraining pipeline\b|\bmodel training\b", re.I), -8, "text"),
        Rule("compiler_kernels_cuda", re.compile(r"\bcompiler\b|\bkernels?\b|\bCUDA\b|\bTPU\b|\bASIC\b", re.I), -5, "text"),
        Rule("theory_math_heavy", re.compile(r"\btheoretical\b|\bproof\b|\bnovel algorithm\b", re.I), -4, "text"),
    ]
    return pos, neg


# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------

def _norm(s: Optional[str]) -> str:
    return (s or "").strip()


def _get_text_blob(job: Dict[str, Any]) -> str:
    """
    Prefer jd_text. If missing, try other possible fields.
    """
    jd = _norm(job.get("jd_text"))
    if jd:
        return jd

    for k in ("description", "description_text", "job_description", "descriptionHtml"):
        v = job.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()

    return ""


def _count_matches(pattern: re.Pattern, s: str) -> int:
    if not s:
        return 0
    matches = list(pattern.finditer(s))
    return min(len(matches), 5)


def _classify_role_band(job: Dict[str, Any]) -> str:
    """
    Classify role band using title + jd_text + department/team strings.
    Priority: CS_CORE -> CS_ADJACENT -> SOLUTIONS -> OTHER (your preference ordering).
    """
    title = _norm(job.get("title"))
    jd = _norm(job.get("jd_text"))
    dept = _norm(job.get("department") or job.get("departmentName"))
    team = _norm(job.get("team"))
    team_names = job.get("teamNames") if isinstance(job.get("teamNames"), list) else []
    team_blob = " ".join([t for t in team_names if isinstance(t, str)])
    combined = " ".join([title, jd, dept, team, team_blob]).lower()

    def has_any(subs: List[str]) -> bool:
        return any(s in combined for s in subs)

    if has_any([
        "customer success", "csm", "success plan", "value realization", "adoption", "onboarding",
        "retention", "renewal", "deployment and adoption", "ai deployment", "support delivery",
    ]):
        return "CS_CORE"

    if has_any([
        "program manager", "delivery lead", "enablement", "engagement", "operations", "gtm", "go to market",
        "account director", "partner", "alliances",
    ]):
        return "CS_ADJACENT"

    if has_any([
        "solutions architect", "solutions engineer", "forward deployed", "field engineer", "pre-sales",
        "presales", "sales engineer", "partner solutions",
    ]):
        return "SOLUTIONS"

    return "OTHER"


def _title_family(title: str) -> str:
    """
    Normalize title into a family bucket for clustering.
    """
    t = _norm(title).lower()
    t = re.sub(r"\s*\([^)]*(remote|san francisco|new york|london|dublin|tokyo|munich|sydney)[^)]*\)\s*$", "", t, flags=re.I)
    t = re.sub(r"\s*[-–—]\s*(sf|nyc|new york|san francisco|london|dublin|tokyo|munich|sydney)\s*$", "", t, flags=re.I)
    t = re.sub(r"\s+", " ", t).strip()
    return t


# ------------------------------------------------------------
# Explainability buckets (Step 1)
# ------------------------------------------------------------

FIT_PATTERNS = [
    ("fit:value_realization", re.compile(r"\bvalue realization\b|\bbusiness value\b|\bROI\b", re.I)),
    ("fit:adoption", re.compile(r"\badoption\b|\bonboarding\b|\benablement\b", re.I)),
    ("fit:stakeholders", re.compile(r"\bstakeholder(s)?\b|\bexecutive\b|\bC-?level\b", re.I)),
    ("fit:post_sales", re.compile(r"\bpost[- ]sales\b|\bcustomer success\b|\brenewal\b|\bretention\b", re.I)),
    ("fit:deployment", re.compile(r"\bdeployment\b|\bimplementation\b|\bintegration\b", re.I)),
]

RISK_PATTERNS = [
    ("risk:phd", re.compile(r"\bPhD\b|\bdoctoral\b", re.I)),
    ("risk:research_heavy", re.compile(r"\bresearch\b|\bnovel algorithm\b|\btheoretical\b", re.I)),
    ("risk:low_level", re.compile(r"\bcompiler\b|\bCUDA\b|\bkernels?\b|\bASIC\b|\bTPU\b", re.I)),
    ("risk:strong_swe_only", re.compile(r"\bC\+\+\b|\brust\b|\boperating systems\b|\bkernel\b", re.I)),
    ("risk:security_clearance", re.compile(r"\b(clearance|ts\/sc|secret|top secret)\b", re.I)),
]


def _signals(text: str, patterns: List[Tuple[str, re.Pattern]]) -> List[str]:
    out: List[str] = []
    for name, pat in patterns:
        if pat.search(text):
            out.append(name)
    return out


# ------------------------------------------------------------
# Scoring
# ------------------------------------------------------------

def score_job(job: Dict[str, Any], pos_rules: List[Rule], neg_rules: List[Rule]) -> Dict[str, Any]:
    title = _norm(job.get("title"))
    text = _get_text_blob(job)
    enrich_status = job.get("enrich_status")  # "enriched" | "unavailable" | etc.

    # If JD unavailable, score title-only lightly.
    title_only_mode = (enrich_status == "unavailable") or (not text)

    base_score = 0
    hits: List[Dict[str, Any]] = []

    def apply_rule(rule: Rule) -> None:
        nonlocal base_score

        if rule.scope == "title":
            hay = title
        elif rule.scope == "text":
            hay = "" if title_only_mode else text
        else:  # either
            hay = title if title_only_mode else (title + "\n" + text)

        c = _count_matches(rule.pattern, hay)
        if c <= 0:
            return

        delta = rule.weight * c
        base_score += delta
        hits.append({"rule": rule.name, "count": c, "delta": delta})

    for r in pos_rules:
        apply_rule(r)
    for r in neg_rules:
        apply_rule(r)

    if (not title_only_mode) and len(text) >= 800:
        base_score += 2
        hits.append({"rule": "has_full_jd_text", "count": 1, "delta": 2})

    # Role band multiplier
    role_band = _classify_role_band(job)
    mult = ROLE_BAND_MULTIPLIERS.get(role_band, 1.0)

    # Profile weights (Step 3): additive nudges
    profile_delta = 0
    if role_band == "CS_CORE":
        profile_delta += PROFILE_WEIGHTS["boost_cs_core"]
    elif role_band == "CS_ADJACENT":
        profile_delta += PROFILE_WEIGHTS["boost_cs_adjacent"]
    elif role_band == "SOLUTIONS":
        profile_delta += PROFILE_WEIGHTS["boost_solutions"]

    # Optional pin for your explicitly mentioned target
    if re.search(r"\bmanager,\s*ai deployment\b", title, re.I):
        profile_delta += PROFILE_WEIGHTS["pin_manager_ai_deployment"]
        hits.append({"rule": "pin_manager_ai_deployment", "count": 1, "delta": PROFILE_WEIGHTS["pin_manager_ai_deployment"]})

    # Risk penalties based on JD/text
    blob = (title if title_only_mode else (title + "\n" + text))
    if re.search(r"\bPhD\b|\bdoctoral\b", blob, re.I):
        profile_delta += PROFILE_WEIGHTS["penalty_research_heavy"]
    if re.search(r"\bcompiler\b|\bCUDA\b|\bkernels?\b|\bASIC\b|\bTPU\b", blob, re.I):
        profile_delta += PROFILE_WEIGHTS["penalty_low_level"]
    if re.search(r"\bC\+\+\b|\brust\b|\boperating systems\b|\bkernel\b", blob, re.I):
        profile_delta += PROFILE_WEIGHTS["penalty_strong_swe_only"]

    score = int(round((base_score + profile_delta) * mult))

    fit_signals = _signals(blob, FIT_PATTERNS)
    risk_signals = _signals(blob, RISK_PATTERNS)

    out = dict(job)
    out["base_score"] = base_score
    out["profile_delta"] = profile_delta
    out["score"] = score
    out["role_band"] = role_band
    out["score_hits"] = sorted(hits, key=lambda x: abs(x["delta"]), reverse=True)
    out["fit_signals"] = fit_signals
    out["risk_signals"] = risk_signals
    out["jd_text_chars"] = len(text)
    out["title_only_mode"] = title_only_mode
    out["title_family"] = _title_family(title)
    return out


def to_csv_rows(scored: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for j in scored:
        top_hits = j.get("score_hits") or []
        top3 = ", ".join([f"{h['rule']}({h['delta']})" for h in top_hits[:3]])
        rows.append({
            "score": j.get("score", 0),
            "base_score": j.get("base_score", 0),
            "profile_delta": j.get("profile_delta", 0),
            "role_band": _norm(j.get("role_band")),
            "title": _norm(j.get("title")),
            "department": _norm(j.get("department") or j.get("departmentName")),
            "team": ", ".join(j.get("teamNames") or []) if isinstance(j.get("teamNames"), list) else _norm(j.get("team")),
            "location": _norm(j.get("location") or j.get("locationName")),
            "enrich_status": _norm(j.get("enrich_status")),
            "enrich_reason": _norm(j.get("enrich_reason")),
            "jd_text_chars": j.get("jd_text_chars", 0),
            "fit_signals": ", ".join(j.get("fit_signals") or []),
            "risk_signals": ", ".join(j.get("risk_signals") or []),
            "apply_url": _norm(j.get("apply_url")),
            "why_top3": top3,
        })
    return rows


# ------------------------------------------------------------
# Step 5: clustering / families output
# ------------------------------------------------------------

def build_families(scored: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    families: Dict[str, Dict[str, Any]] = {}
    variants: Dict[str, List[Dict[str, Any]]] = {}

    for j in scored:
        fam = _norm(j.get("title_family"))
        if not fam:
            fam = _title_family(_norm(j.get("title")))
        if not fam:
            fam = _norm(j.get("title")).lower()

        variants.setdefault(fam, []).append({
            "title": _norm(j.get("title")),
            "location": _norm(j.get("location") or j.get("locationName")),
            "apply_url": _norm(j.get("apply_url")),
            "score": j.get("score", 0),
            "role_band": _norm(j.get("role_band")),
        })

        if fam not in families or j.get("score", 0) > families[fam].get("score", 0):
            families[fam] = dict(j)

    out: List[Dict[str, Any]] = []
    for fam, best in families.items():
        entry = dict(best)
        entry["title_family"] = fam
        entry["family_variants"] = variants.get(fam, [])
        out.append(entry)

    out.sort(key=lambda x: x.get("score", 0), reverse=True)
    return out


# ------------------------------------------------------------
# Step 8: shortlist output
# ------------------------------------------------------------

def write_shortlist_md(scored: List[Dict[str, Any]], out_path: Path, min_score: int) -> None:
    shortlist = [
        j for j in scored
        if j.get("score", 0) >= min_score and j.get("enrich_status") != "unavailable"
    ]

    lines: List[str] = ["# OpenAI Shortlist", f"", f"Min score: **{min_score}**", ""]
    for job in shortlist:
        title = _norm(job.get("title")) or "Untitled"
        score = job.get("score", 0)
        role_band = _norm(job.get("role_band"))
        apply_url = _norm(job.get("apply_url"))

        lines.append(f"## {title} — {score} [{role_band}]")
        if apply_url:
            lines.append(f"[Apply link]({apply_url})")

        fit = job.get("fit_signals") or []
        risk = job.get("risk_signals") or []
        if fit:
            lines.append("**Fit signals:** " + ", ".join(fit))
        if risk:
            lines.append("**Risk signals:** " + ", ".join(risk))

        hits = job.get("score_hits") or []
        reasons = [h.get("rule") for h in hits[:5] if h.get("rule")]
        if reasons:
            lines.append("**Top rules:** " + ", ".join(reasons))

        jd = _norm(job.get("jd_text"))
        if jd:
            excerpt = jd[:700] + ("…" if len(jd) > 700 else "")
            lines.append("")
            lines.append(excerpt)

        lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")

def is_us_or_remote_us(job: Dict[str, Any]) -> bool:
    loc = (job.get("location") or job.get("locationName") or "").strip().lower()

    # allow remote only if explicitly US
    if "remote" in loc:
        return "us" in loc or "united states" in loc

    # common non-US markers to exclude
    non_us_markers = [
        "london", "uk", "united kingdom",
        "dublin", "ireland",
        "tokyo", "japan",
        "munich", "germany",
        "sydney", "australia",
        "emea", "apac", "singapore", "paris", "france", "canada",
    ]
    if any(x in loc for x in non_us_markers):
        return False

    # If it isn't clearly non-US and isn't remote, assume it's US (works well for SF/NYC/DC etc)
    return bool(loc)

# ------------------------------------------------------------
# Main
# ------------------------------------------------------------



def main() -> int:
    if not logging.getLogger().hasHandlers():
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    ap = argparse.ArgumentParser()

    ap.add_argument("--profile", default="cs")
    ap.add_argument("--profiles", default="config/profiles.json")
    ap.add_argument("--in_path", default=str(ENRICHED_JOBS_JSON))

    ap.add_argument("--out_json", default=str(ranked_jobs_json("cs")))
    ap.add_argument("--out_csv", default=str(ranked_jobs_csv("cs")))
    ap.add_argument("--out_families", default=str(ranked_families_json("cs")))
    ap.add_argument("--out_md", default=str(shortlist_md("cs")))

    ap.add_argument("--shortlist_score", type=int, default=70)
    ap.add_argument("--us_only", action="store_true")
    args = ap.parse_args()

    # ---- HARDEN OUTPUT PATHS ----
    out_json = Path(args.out_json)
    out_csv = Path(args.out_csv)
    out_families = Path(args.out_families)
    out_md = Path(args.out_md)

    for p in [out_json, out_csv, out_families, out_md]:
        if "<function " in str(p):
            raise SystemExit(f"Refusing invalid output path (looks like function repr): {p}")

    out_json.parent.mkdir(parents=True, exist_ok=True)
    # ----------------------------

    profiles = load_profiles(args.profiles)
    apply_profile(args.profile, profiles)

    in_path = Path(args.in_path)
    if not in_path.exists():
        raise SystemExit(f"Input not found: {in_path}")

    jobs = json.loads(in_path.read_text(encoding="utf-8"))
    if not isinstance(jobs, list):
        raise SystemExit("Input JSON must be a list of jobs")

    if args.us_only:
        before = len(jobs)
        jobs = [j for j in jobs if is_us_or_remote_us(j)]
        logger.info(f"US-only filter: {before} -> {len(jobs)} jobs")

    pos_rules, neg_rules = _compile_rules()
    scored = [score_job(j, pos_rules, neg_rules) for j in jobs]
    scored.sort(key=lambda x: x.get("score", 0), reverse=True)

    out_json.write_text(json.dumps(scored, ensure_ascii=False, indent=2), encoding="utf-8")

    rows = to_csv_rows(scored)
    with out_csv.open("w", encoding="utf-8", newline="") as f:
        if rows:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)

    families = build_families(scored)
    out_families.write_text(json.dumps(families, ensure_ascii=False, indent=2), encoding="utf-8")

    write_shortlist_md(scored, out_md, min_score=args.shortlist_score)

    logger.info(f"Wrote ranked JSON     : {out_json}")
    logger.info(f"Wrote ranked CSV      : {out_csv}")
    logger.info(f"Wrote ranked families : {out_families}")
    logger.info(f"Wrote shortlist MD    : {out_md} (score >= {args.shortlist_score})")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

