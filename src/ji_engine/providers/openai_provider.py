from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

import requests
from bs4 import BeautifulSoup
from bs4.element import Tag

from ji_engine.models import RawJobPosting, JobSource
from ji_engine.providers.base import BaseJobProvider


CAREERS_SEARCH_URL = "https://openai.com/careers/search/"
SNAPSHOT_DIR = Path("data") / "openai_snapshots"
SNAPSHOT_FILE = SNAPSHOT_DIR / "index.html"


class OpenAICareersProvider(BaseJobProvider):
    """
    Provider for OpenAI careers.

    For now we prioritize SNAPSHOT mode because the live site returns 403
    to our requests client. Live scraping is a best-effort bonus.

    In SNAPSHOT mode, we expect:
        data/openai_snapshots/index.html
    to be a page you manually saved from your browser.
    """

    def scrape_live(self) -> List[RawJobPosting]:
        """
        Attempt a live HTTP scrape.

        This will likely hit 403 due to WAF. We keep it simple and let the
        BaseJobProvider handle fallback to snapshot.
        """
        headers = {
            "User-Agent": "job-intelligence-engine/0.1 (+personal project)",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        resp = requests.get(CAREERS_SEARCH_URL, headers=headers, timeout=20)
        if resp.status_code != 200:
            raise RuntimeError(
                f"Live scrape failed with status {resp.status_code} at {CAREERS_SEARCH_URL}"
            )
        html = resp.text
        return self._parse_html(html)

    def load_from_snapshot(self) -> List[RawJobPosting]:
        SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)

        if not SNAPSHOT_FILE.exists():
            print(f"[OpenAICareersProvider] ❌ Snapshot not found at {SNAPSHOT_FILE}")
            print(
                "Save https://openai.com/careers/search/ as 'index.html' in "
                "data/openai_snapshots/ and rerun."
            )
            return []

        print(f"[OpenAICareersProvider] 📂 Using snapshot {SNAPSHOT_FILE}")
        html = SNAPSHOT_FILE.read_text(encoding="utf-8")
        return self._parse_html(html)

    # ---------- Core HTML parsing ----------

    def _parse_html(self, html: str) -> List[RawJobPosting]:
        """
        Parse the saved careers page HTML and extract job postings with best-effort descriptions.

        Extracts:
        - Job title
        - Apply URL (Ashby links)
        - Detail URL (if different from apply URL)
        - Best-effort job description text
        - Location and team (if available in HTML)
        """
        soup = BeautifulSoup(html, "html.parser")
        results: List[RawJobPosting] = []
        now = datetime.utcnow()

        # Find all job links (Ashby job application links)
        apply_links = soup.find_all("a", href=lambda h: h and "jobs.ashbyhq.com" in h)

        for apply_tag in apply_links:
            if not isinstance(apply_tag, Tag):
                continue

            apply_url = apply_tag.get("href", "")

            title = self._extract_title(apply_tag)
            detail_url = self._extract_detail_url(apply_tag, apply_url)
            location, team = self._extract_metadata(apply_tag)
            job_description = self._extract_job_description(apply_tag)

            posting = RawJobPosting(
                source=JobSource.OPENAI,
                title=title,
                location=location,
                team=team,
                apply_url=apply_url,
                detail_url=detail_url,
                raw_text=job_description,
                scraped_at=now,
            )
            results.append(posting)

        print(f"[OpenAICareersProvider] Parsed {len(results)} jobs from HTML")
        return results

    # ---------- Helpers ----------

    def _extract_title(self, apply_tag: Tag) -> str:
        """Extract job title from the HTML structure near the apply link."""
        # Try to find a title link or heading near the apply tag
        title_tag = apply_tag.find_previous("a")
        if title_tag is not None and title_tag is not apply_tag:
            title_text = title_tag.get_text(strip=True)
            if title_text:
                return title_text

        # Look for heading elements (h1-h6) in parent containers
        parent = apply_tag.parent
        for _ in range(3):  # Check up to 3 levels up
            if parent is None:
                break
            heading = parent.find(["h1", "h2", "h3", "h4", "h5", "h6"])
            if heading is not None:
                title_text = heading.get_text(strip=True)
                if title_text:
                    return title_text
            parent = parent.parent

        # Fallback to apply tag text
        title_text = apply_tag.get_text(strip=True)
        return title_text if title_text else "Untitled Position"

    def _extract_detail_url(self, apply_tag: Tag, apply_url: str) -> Optional[str]:
        """Extract detail URL if different from apply URL."""
        title_tag = apply_tag.find_previous("a")
        if title_tag is not None and title_tag is not apply_tag:
            detail_url = title_tag.get("href")
            if detail_url and detail_url != apply_url:
                return detail_url
        return apply_url

    def _extract_metadata(self, apply_tag: Tag) -> Tuple[Optional[str], Optional[str]]:
        """Extract location and team metadata from HTML structure."""
        location: Optional[str] = None
        team: Optional[str] = None

        parent = apply_tag.parent
        for _ in range(5):  # Check up to 5 levels up
            if parent is None:
                break

            # Look for common location/team indicators
            text = parent.get_text()

            if not location:
                location_elem = parent.find(
                    string=lambda s: s
                    and any(
                        loc_indicator in s.lower()
                        for loc_indicator in ["location", "based in", "remote", "hybrid"]
                    )
                )
                if location_elem:
                    location_text = (
                        location_elem.parent.get_text(strip=True)
                        if getattr(location_elem, "parent", None)
                        else None
                    )
                    if location_text:
                        location = (
                            location_text.split(":", 1)[-1].strip()
                            if ":" in location_text
                            else location_text
                        )

            if not team:
                team_elem = parent.find(
                    string=lambda s: s
                    and any(
                        team_indicator in s.lower()
                        for team_indicator in ["team", "department", "division"]
                    )
                )
                if team_elem:
                    team_text = (
                        team_elem.parent.get_text(strip=True)
                        if getattr(team_elem, "parent", None)
                        else None
                    )
                    if team_text:
                        team = (
                            team_text.split(":", 1)[-1].strip()
                            if ":" in team_text
                            else team_text
                        )

            parent = parent.parent

        return location, team

     def _extract_job_description(self, apply_tag, soup: BeautifulSoup) -> str:
        """
        Simpler description extractor:

        - Look in the nearest job-card container.
        - Take paragraphs / divs that look like content.
        - Strip obvious UI noise.
        """
        # 1) Find a reasonably small container around this link
        container = apply_tag.find_parent(["div", "article", "section", "li", "tr"])
        if not container:
            title = self._extract_title(apply_tag)
            return f"Job Title: {title}\n\nFull job description not found in snapshot HTML."

        raw_text = container.get_text(separator="\n", strip=True)

        # 2) Remove common noise
        lines = []
        for line in raw_text.split("\n"):
            lower = line.lower().strip()
            if not line:
                continue
            if any(phrase in lower for phrase in ["apply now", "learn more", "view job"]):
                continue
            if len(line) < 10:
                continue
            lines.append(line)

        if not lines:
            title = self._extract_title(apply_tag)
            return f"Job Title: {title}\n\nFull job description not found in snapshot HTML."

        desc = "\n".join(lines)

        # 3) If still super short, fall back to title-only
        if len(desc) < 80:
            title = self._extract_title(apply_tag)
            return f"Job Title: {title}\n\nDescription in snapshot is very short."

        return desc

