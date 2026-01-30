"""Enrich job postings by fetching job data via Ashby API/GraphQL instead of parsing HTML."""

import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from bs4 import BeautifulSoup

from ji_engine.utils.job_id import extract_job_id_from_url

# Debug mode flag
DEBUG = os.getenv("JI_DEBUG") == "1"

ASHBY_GQL_URL = "https://jobs.ashbyhq.com/api/non-user-graphql?op=ApiJobPosting"

# Exact known-good query for Ashby non-user GraphQL
ASHBY_API_JOBPOSTING_QUERY = """query ApiJobPosting($organizationHostedJobsPageName: String!, $jobPostingId: String!) {
  jobPosting(
    organizationHostedJobsPageName: $organizationHostedJobsPageName
    jobPostingId: $jobPostingId
  ) {
    id
    title
    departmentName
    locationName
    workplaceType
    employmentType
    descriptionHtml
    teamNames
  }
}"""


def _get_json_cache_path(cache_dir: Path, job_id: str) -> Path:
    """Get the JSON cache file path for a job ID."""
    return cache_dir / f"{job_id}.json"


def _load_json_cache(cache_dir: Path, job_id: str) -> Optional[Dict[str, Any]]:
    """Load cached JSON response for a job ID."""
    json_cache_path = _get_json_cache_path(cache_dir, job_id)
    if not json_cache_path.exists():
        return None

    try:
        return json.loads(json_cache_path.read_text(encoding="utf-8"))
    except Exception as e:
        if DEBUG:
            print(f"      Failed to load cached JSON: {e}")
        return None


def _save_json_cache(cache_dir: Path, job_id: str, data: Dict[str, Any]) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    json_cache_path = _get_json_cache_path(cache_dir, job_id)
    json_cache_path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _extract_job_id_from_url(url: str) -> Optional[str]:
    """
    Extract jobPostingId from apply_url using regex pattern.

    Pattern: /openai/([0-9a-f-]{36})/application
    Example: https://jobs.ashbyhq.com/openai/0c22b805-3976-492e-81f2-7cf91f63a630/application
    """
    return extract_job_id_from_url(url)


def _html_to_text(description_html: str) -> str:
    """Convert descriptionHtml to readable text."""
    soup = BeautifulSoup(description_html, "html.parser")
    # Keep line breaks reasonably
    return soup.get_text(separator="\n", strip=True)


def _fetch_html_no_cache(url: str) -> Optional[str]:
    """Fetch HTML from URL without caching (fallback only)."""
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=20)
        resp.raise_for_status()
        html = resp.text
        html_lower = html.lower()
        if "<html" not in html_lower and "<!doctype" not in html_lower:
            if DEBUG:
                print(f"      ⚠️  HTML fallback response doesn't look like HTML for {url}")
            return None
        return html
    except Exception as e:
        print(f"      ⚠️  Failed to fetch HTML fallback for {url}: {e}")
        return None


def _fetch_job_data_from_api(job_id: str, api_endpoint: str, cache_dir: Path) -> Optional[Dict[str, Any]]:
    """
    Fetch job data from Ashby GraphQL API using the correct ApiJobPosting operation.
    Caches ONLY valid responses to data/ashby_cache/{job_id}.json
    """
    cache_dir.mkdir(parents=True, exist_ok=True)

    # 1) Try cache, but only accept it if it looks valid
    cached = _load_json_cache(cache_dir, job_id)
    if isinstance(cached, dict):
        jp = (cached.get("data") or {}).get("jobPosting")
        if isinstance(jp, dict) and jp.get("id"):
            if DEBUG:
                print(f"      Using cached JSON for job_id: {job_id}")
            return cached
        else:
            if DEBUG:
                print(f"      Ignoring cached JSON for job_id {job_id} (invalid shape)")

    # 2) Real payload (captured from Network tab)
    payload = {
        "operationName": "ApiJobPosting",
        "variables": {
            "organizationHostedJobsPageName": "openai",
            "jobPostingId": job_id,
        },
        "query": """
    query ApiJobPosting(
      $organizationHostedJobsPageName: String!,
      $jobPostingId: String!
    ) {
      jobPosting(
        organizationHostedJobsPageName: $organizationHostedJobsPageName
        jobPostingId: $jobPostingId
      ) {
        id
        title
        departmentName
        locationName
        workplaceType
        employmentType
        descriptionHtml
        teamNames
      }
    }
    """,
    }

    headers = {
        "content-type": "application/json",
        "accept": "application/json",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:146.0) Gecko/20100101 Firefox/146.0",
        "referer": f"https://jobs.ashbyhq.com/openai/{job_id}/application",
        "origin": "https://jobs.ashbyhq.com",
        "apollographql-client-name": "frontend_non_user",
        "apollographql-client-version": "0.1.0",
    }

    try:
        resp = requests.post(api_endpoint, headers=headers, json=payload, timeout=30)

        if resp.status_code != 200:
            print(f"      ⚠️  API status {resp.status_code} for job_id {job_id}")
            print(f"      Body preview: {resp.text[:200]}")
        resp.raise_for_status()

        data = resp.json()

        if "errors" in data:
            print("      ❌ GraphQL errors — not caching")
            return None

        # 3) Validate: must contain a real jobPosting object
        jp = (data.get("data") or {}).get("jobPosting") if isinstance(data, dict) else None
        if not isinstance(jp, dict) or not jp.get("id"):
            print(f"      ⚠️  API response missing data.jobPosting for {job_id}")
            if isinstance(data, dict) and data.get("errors"):
                print(f"      Errors preview: {data['errors'][:2]}")
            return None

        # 4) Cache only valid responses
        json_cache_path = _get_json_cache_path(cache_dir, job_id)
        json_cache_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

        return data

    except Exception as e:
        print(f"      ⚠️  API request failed for {job_id}: {e}")
        return None


def _parse_job_data_from_json(api_data: Dict[str, Any]) -> Dict[str, Optional[str]]:
    jp = (api_data.get("data") or {}).get("jobPosting") or {}

    title = jp.get("title")
    location = jp.get("locationName")

    team = None
    team_names = jp.get("teamNames")
    if isinstance(team_names, list) and team_names:
        team = ", ".join([t for t in team_names if isinstance(t, str) and t.strip()]) or None

    jd_html = (jp.get("descriptionHtml") or "").strip()
    jd_text = jd_html if jd_html else None

    return {
        "title": title,
        "location": location,
        "team": team,
        "jd_text": jd_text,
    }


def extract_jd_text_from_html(html: str) -> Optional[str]:
    """Extract job description text from HTML (fallback method)."""
    soup = BeautifulSoup(html, "html.parser")

    # As a crude fallback, grab visible text
    for tag in soup.find_all(["script", "style", "nav", "header", "footer"]):
        tag.decompose()
    text = soup.get_text(separator="\n", strip=True)
    return text if text and len(text) > 200 else None


def extract_clean_title_from_html(html: str) -> Optional[str]:
    """Extract clean job title from HTML (fallback method)."""
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.find("h1")
    if h1:
        t = h1.get_text(strip=True)
        if t:
            return t
    return None


def enrich_jobs(
    labeled_jobs: List[Dict[str, Any]],
    cache_dir: Path,
    rate_limit: float = 1.0,
) -> List[Dict[str, Any]]:
    """
    Enrich labeled jobs by fetching job data via Ashby API, falling back to HTML parsing.
    """
    enriched: List[Dict[str, Any]] = []

    for i, job in enumerate(labeled_jobs, 1):
        apply_url = job.get("apply_url", "")
        job_id = job.get("job_id") or extract_job_id_from_url(apply_url)
        if not apply_url:
            print(f"  [{i}/{len(labeled_jobs)}] Skipping - no apply_url")
            enriched.append({**job, "job_id": job_id, "jd_text": None, "fetched_at": None})
            continue

        print(f"  [{i}/{len(labeled_jobs)}] Processing: {job.get('title', 'Unknown')}")

        job_id = job_id or _extract_job_id_from_url(apply_url)
        if not job_id:
            print("    ⚠️  Cannot extract jobPostingId from URL - not enrichable")
            print(f"    URL: {apply_url}")
            enriched.append({**job, "job_id": job_id, "jd_text": None, "fetched_at": None})
            continue

        api_data = _fetch_job_data_from_api(job_id, ASHBY_GQL_URL, cache_dir)

        clean_title = job.get("title")
        location = job.get("location")
        team = job.get("team")
        jd_text: Optional[str] = None

        if api_data:
            parsed = _parse_job_data_from_json(api_data)
            clean_title = parsed["title"] or clean_title
            location = parsed["location"] or location
            team = parsed["team"] or team
            jd_text = parsed["jd_text"]

            if jd_text:
                print(f"    ✅ Extracted via API: {len(jd_text)} chars")
            else:
                print("    ⚠️  API response missing descriptionHtml (unexpected)")

        # HTML fallback only if API failed or missing JD text
        if not jd_text:
            print("    ⚠️  Falling back to HTML parsing")
            html = _fetch_html_no_cache(apply_url)
            if html:
                jd_text = extract_jd_text_from_html(html)
                if not clean_title:
                    clean_title = extract_clean_title_from_html(html) or clean_title

        fetched_at = datetime.utcnow().isoformat()
        if jd_text:
            print(f"    ✅ Final JD length: {len(jd_text)} chars")
        else:
            print("    ❌ No JD text extracted")

        enriched.append(
            {
                **job,
                "job_id": job_id,
                "title": clean_title,
                "location": location,
                "team": team,
                "jd_text": jd_text,
                "fetched_at": fetched_at,
            }
        )

        # Rate limit only when we're actually hitting API (not when using cached JSON)
        # We can approximate by sleeping when cache file didn't exist before.
        # (Simple + good enough for now)
        if i < len(labeled_jobs):
            time.sleep(rate_limit)

    return enriched
