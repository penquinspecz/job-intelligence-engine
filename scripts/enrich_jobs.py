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

import argparse
import json
import logging
import os
import sys
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from bs4 import BeautifulSoup

from ji_engine.config import ASHBY_CACHE_DIR, ENRICHED_JOBS_JSON, LABELED_JOBS_JSON
from ji_engine.integrations.ashby_graphql import fetch_job_posting
from ji_engine.integrations.html_to_text import html_to_text
from ji_engine.utils.atomic_write import atomic_write_text
from collections import Counter

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
                print(" descriptionHtml converted to empty text - treating as unavailable")
            updated["enrich_status"] = "unavailable"
            updated["enrich_reason"] = "empty_description"
            updated.update({"title": clean_title, "location": location, "team": team, "jd_text": None})
            return updated, False

    if DEBUG:
        logger.info(" descriptionHtml missing/empty; treating as unavailable")
        logger.info(f" fallback_url: {fallback_url}")
    updated["enrich_status"] = "unavailable"
    updated["enrich_reason"] = "empty_description"
    updated.update({"title": clean_title, "location": location, "team": team, "jd_text": None})
    return updated, False


def _enrich_single(
    job: Dict[str, Any],
    index: int,
    total: int,
    fetch_func=fetch_job_posting,
) -> Tuple[Dict[str, Any], Optional[str], str]:
    """
    Enrich a single job. Returns (updated_job, unavailable_reason, status_key)
    status_key in {"enriched", "unavailable", "failed"} for stats aggregation.
    """
    apply_url = job.get("apply_url", "")
    if not apply_url:
        logger.info(f" [{index}/{total}] Skipping - no apply_url")
        updated_job = {**job, "jd_text": None, "fetched_at": None}
        return updated_job, None, "failed"

    logger.info(f" [{index}/{total}] Processing: {job.get('title', 'Unknown')}")

    job_id = _extract_job_id_from_url(apply_url)
    if not job_id:
        logger.info(" ⚠️ Cannot extract jobPostingId from URL - not enrichable")
        logger.info(f" URL: {apply_url}")
        updated_job = {**job, "jd_text": None, "fetched_at": None}
        return updated_job, None, "failed"

    fallback_url = _derive_fallback_url(apply_url)

    try:
        api_data = fetch_func(org=ORG, job_id=job_id, cache_dir=CACHE_DIR)
    except Exception as e:
        logger.info(f" ❌ API fetch failed: {e}")
        api_data = None

    updated_job, fallback_needed = _apply_api_response(job, api_data, fallback_url)
    jd_text = updated_job.get("jd_text")
    unavailable_reason: Optional[str] = None

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
                logger.info(" ❌ HTML extraction failed (empty text)")
                updated_job["enrich_status"] = "unavailable"
                updated_job["enrich_reason"] = "empty_description"
        else:
            logger.info(" ❌ HTML fetch failed")
            updated_job["enrich_status"] = updated_job.get("enrich_status") or "failed"
            updated_job["enrich_reason"] = updated_job.get("enrich_reason") or "html_fetch_failed"

    if updated_job.get("enrich_status") == "unavailable":
        jd_text = None
        unavailable_reason = updated_job.get("enrich_reason") or "unavailable"

    updated_job["fetched_at"] = datetime.utcnow().isoformat()

    if jd_text:
        logger.info(f" ✅ Final JD length: {len(jd_text)} chars")
        status_key = "enriched"
    else:
        status = updated_job.get("enrich_status")
        if status == "unavailable":
            status_key = "unavailable"
        else:
            status_key = "failed"
        logger.info(" ❌ No JD text extracted")

    return updated_job, unavailable_reason, status_key


def main(argv: Optional[List[str]] = None) -> int:
    if not logging.getLogger().hasHandlers():
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    ap = argparse.ArgumentParser()
    default_max_workers = int(os.getenv("ENRICH_MAX_WORKERS", "4"))
    default_limit_env = os.getenv("ENRICH_LIMIT")
    ap.add_argument("--max_workers", type=int, default=default_max_workers, help="Max threads for enrichment")
    ap.add_argument(
        "--limit",
        type=int,
        default=int(default_limit_env) if default_limit_env else None,
        help="Limit number of jobs to enrich (for tests/dev).",
    )
    ap.add_argument("--in_path", help="Input labeled jobs JSON (default: config LABELED_JOBS_JSON)")
    ap.add_argument("--out_path", help="Output enriched jobs JSON (default: config ENRICHED_JOBS_JSON)")
    args = ap.parse_args(argv)

    in_path = Path(args.in_path) if args.in_path else LABELED_JOBS_JSON
    if not in_path.exists():
        logger.error(f"Error: Input file not found: {in_path}")
        return 1

    jobs = json.loads(in_path.read_text(encoding="utf-8"))
    enriched: List[Dict[str, Any]] = []
    stats = {"enriched": 0, "unavailable": 0, "failed": 0}
    unavailable_reasons: Counter[str] = Counter()

    filtered_jobs = [j for j in jobs if j.get("relevance") in ("RELEVANT", "MAYBE")]
    if args.limit is not None:
        filtered_jobs = filtered_jobs[: max(0, args.limit)]

    logger.info(f"Loaded {len(jobs)} labeled jobs")
    logger.info(f"Filtering for RELEVANT/MAYBE: {len(filtered_jobs)} jobs to enrich\n")

    with ThreadPoolExecutor(max_workers=max(1, args.max_workers)) as pool:
        futures = []
        for i, job in enumerate(filtered_jobs, 1):
            futures.append((i, pool.submit(_enrich_single, job, i, len(filtered_jobs), fetch_job_posting)))

        # preserve deterministic ordering by index
        results: List[Tuple[int, Dict[str, Any], Optional[str], str]] = []
        for i, fut in futures:
            updated_job, unavailable_reason, status_key = fut.result()
            results.append((i, updated_job, unavailable_reason, status_key))

    results.sort(key=lambda x: x[0])
    for _, updated_job, unavailable_reason, status_key in results:
        if status_key == "enriched":
            stats["enriched"] += 1
        elif status_key == "unavailable":
            stats["unavailable"] += 1
        else:
            stats["failed"] += 1

        if unavailable_reason:
            unavailable_reasons[unavailable_reason] += 1

        enriched.append(updated_job)

    out_path = Path(args.out_path) if args.out_path else ENRICHED_JOBS_JSON
    out_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(out_path, json.dumps(enriched, ensure_ascii=False, indent=2))

    logger.info("\n" + "=" * 60)
    logger.info("Enrichment Summary:")
    logger.info(f" Total processed: {len(enriched)}")
    logger.info(f" Enriched: {stats['enriched']}")
    logger.info(f" Unavailable: {stats['unavailable']}")
    logger.info(f" Failed: {stats['failed']}")
    if unavailable_reasons:
        reason_str = ", ".join([f"{k}={v}" for k, v in sorted(unavailable_reasons.items())])
        logger.info(f" Unavailable reasons: {reason_str}")
    logger.info(f" Output: {out_path}")
    logger.info("=" * 60)

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
