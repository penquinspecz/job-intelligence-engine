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

    def fetch_jobs(self) -> List[RawJobPosting]:
        """
        Use snapshot mode when requested; in LIVE mode fetch HTML, persist a
        snapshot, then parse.
        """
        if self.mode == "SNAPSHOT":
            return self.load_from_snapshot()

        # LIVE path: best effort fetch, then persist snapshot for reuse
        try:
            html = self._fetch_live_html()
        except Exception as e:
            print(f"[OpenAICareersProvider] LIVE blocked ({e}). Using snapshot.")
            return self.load_from_snapshot()

        SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
        SNAPSHOT_FILE.write_text(html, encoding="utf-8")
        return self._parse_html(html)

    def scrape_live(self) -> List[RawJobPosting]:
        """
        Attempt a live HTTP scrape, saving the HTML snapshot for reuse.
        """
        html = self._fetch_live_html()

        SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
        SNAPSHOT_FILE.write_text(html, encoding="utf-8")

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

    def _fetch_live_html(self) -> str:
        """
        Fetch the careers page HTML from the live site.
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
        return resp.text

    # ---------- Core HTML parsing ----------

    def _parse_html(self, html: str) -> List[RawJobPosting]:
        """
        Parse the saved careers page HTML using DOM targeting.

        Strategy:
        (a) Locate each job card/list item
        (b) Within each card, identify anchor with href containing jobs.ashbyhq.com/openai/ as apply_url
        (c) Set title to nearest preceding heading/anchor representing job title
        (d) Extract department and location from specific sibling nodes/spans
        (e) Return one RawJobPosting per card (dedupe by apply_url)
        """
        soup = BeautifulSoup(html, "html.parser")
        results: List[RawJobPosting] = []
        seen_apply_urls: set[str] = set()
        now = datetime.utcnow()

        # Find all job cards/list items - common patterns
        job_cards = soup.find_all(
            ["li", "div", "article", "section"],
            class_=lambda c: c and any(
                keyword in c.lower()
                for keyword in ["job", "card", "posting", "position", "role", "listing"]
            ),
        )

        # If no cards found with class hints, try finding cards by structure
        if not job_cards:
            # Look for containers that have Ashby links inside
            apply_links = soup.find_all("a", href=lambda h: h and "jobs.ashbyhq.com/openai/" in h)
            for link in apply_links:
                if not isinstance(link, Tag):
                    continue
                # Find the containing card
                card = link.find_parent(["li", "div", "article", "section", "tr"])
                if card and card not in job_cards:
                    job_cards.append(card)

        # Process each job card
        for card in job_cards:
            if not isinstance(card, Tag):
                continue

            # (b) Find apply_url anchor within this card
            apply_link = card.find("a", href=lambda h: h and "jobs.ashbyhq.com/openai/" in h)
            if not apply_link or not isinstance(apply_link, Tag):
                continue

            apply_url = apply_link.get("href", "").strip()
            if not apply_url or apply_url in seen_apply_urls:
                continue  # Dedupe by apply_url
            seen_apply_urls.add(apply_url)

            # (c) Extract title from nearest preceding heading/anchor
            raw_title = self._extract_title_from_card(card, apply_link)

            # (d) Extract department/team and location from sibling nodes/spans
            team = self._extract_team_from_card(card)
            location = self._extract_location_from_card(card)

            # Sanitize title to avoid concatenated department/location
            title = self._sanitize_title(raw_title, team, location)
            if not title:
                title = raw_title or "Untitled Position"

            # Extract detail_url if different from apply_url
            detail_url = self._extract_detail_url_from_card(card, apply_url)

            # Extract job description (minimal, just for raw_text field)
            job_description = self._extract_job_description_from_card(card, title)

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

    def _extract_title_from_card(self, card: Tag, apply_link: Tag) -> str:
        """
        Extract job title from card using DOM targeting.
        Looks for nearest preceding heading or anchor (not the apply link itself).
        """
        # Prefer dedicated title elements if present (common Ashby data-testid)
        title_el = card.find(attrs={"data-testid": lambda v: v and "title" in v.lower()})
        if isinstance(title_el, Tag):
            text = title_el.get_text(strip=True)
            if text:
                return text

        # Look for headings (h1-h6) in the card, before the apply link
        for heading in card.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
            if heading.get_text(strip=True):
                # Check if heading comes before apply_link in document order
                if self._element_before(heading, apply_link):
                    title = heading.get_text(strip=True)
                    if title and title.lower() not in ["apply", "apply now", "view job"]:
                        return title

        # Look for anchor tags that might be title links (not the apply link)
        for anchor in card.find_all("a"):
            if anchor is apply_link:
                continue
            href = anchor.get("href", "")
            # Skip if it's another apply link
            if "jobs.ashbyhq.com" in href:
                continue
            if self._element_before(anchor, apply_link):
                title = anchor.get_text(strip=True)
                if title and len(title) > 3:
                    return title

        # Fallback: look for any strong/bold text before apply link
        for strong in card.find_all(["strong", "b"]):
            if self._element_before(strong, apply_link):
                title = strong.get_text(strip=True)
                if title and len(title) > 3:
                    return title

        # Last resort: use apply link text if it's meaningful
        apply_text = apply_link.get_text(strip=True)
        if apply_text and len(apply_text) > 10:
            return apply_text

        return "Untitled Position"

    def _sanitize_title(self, title: str, team: Optional[str], location: Optional[str]) -> str:
        """
        Remove concatenated department/location suffixes with no separator.
        Examples: 'Field EngineerRoboticsSan Francisco' -> 'Field Engineer'
        """
        if not title:
            return title

        sanitized = title

        def strip_suffix(text: str, suffix: str) -> str:
            if text.endswith(suffix):
                return text[: -len(suffix)].strip()
            return text

        if team and location:
            combo = f"{team}{location}"
            if combo and combo in sanitized:
                sanitized = sanitized.replace(combo, "").strip()
                return sanitized
            sanitized = strip_suffix(sanitized, combo)

        if team:
            sanitized = strip_suffix(sanitized, team)
        if location:
            sanitized = strip_suffix(sanitized, location)

        return sanitized if sanitized else title

    def _extract_team_from_card(self, card: Tag) -> Optional[str]:
        """Extract department/team from card using DOM targeting."""
        # Look for spans/divs with class hints
        for elem in card.find_all(["span", "div", "p"]):
            class_attr = elem.get("class", [])
            class_str = " ".join(class_attr).lower() if class_attr else ""
            if any(keyword in class_str for keyword in ["team", "department", "dept", "group"]):
                text = elem.get_text(strip=True)
                if text and len(text) < 100:  # Reasonable team name length
                    # Clean up common prefixes
                    for prefix in ["team:", "department:", "dept:", "group:"]:
                        if text.lower().startswith(prefix):
                            text = text[len(prefix):].strip()
                    return text

        # Look for text patterns like "Team: X" or "Department: Y"
        for elem in card.find_all(["span", "div", "p"]):
            text = elem.get_text(strip=True)
            if not text:
                continue
            text_lower = text.lower()
            for pattern in ["team:", "department:", "dept:"]:
                if pattern in text_lower:
                    parts = text.split(":", 1)
                    if len(parts) == 2:
                        team = parts[1].strip()
                        if team and len(team) < 100:
                            return team

        return None

    def _extract_location_from_card(self, card: Tag) -> Optional[str]:
        """Extract location from card using DOM targeting."""
        # Look for spans/divs with class hints
        for elem in card.find_all(["span", "div", "p"]):
            class_attr = elem.get("class", [])
            class_str = " ".join(class_attr).lower() if class_attr else ""
            if any(keyword in class_str for keyword in ["location", "loc", "city", "office", "place"]):
                text = elem.get_text(strip=True)
                if text and len(text) < 100:  # Reasonable location length
                    # Clean up common prefixes
                    for prefix in ["location:", "loc:", "city:", "office:"]:
                        if text.lower().startswith(prefix):
                            text = text[len(prefix):].strip()
                    return text

        # Look for text patterns like "Location: X"
        for elem in card.find_all(["span", "div", "p"]):
            text = elem.get_text(strip=True)
            if not text:
                continue
            text_lower = text.lower()
            for pattern in ["location:", "loc:", "based in:"]:
                if pattern in text_lower:
                    parts = text.split(":", 1)
                    if len(parts) == 2:
                        location = parts[1].strip()
                        if location and len(location) < 100:
                            return location

        return None

    def _extract_detail_url_from_card(self, card: Tag, apply_url: str) -> Optional[str]:
        """Extract detail URL if different from apply URL."""
        # Look for title links that might be detail pages
        for anchor in card.find_all("a"):
            href = anchor.get("href", "")
            if href and href != apply_url and "jobs.ashbyhq.com" not in href:
                # Might be a detail page
                return href
        return None

    def _extract_job_description_from_card(self, card: Tag, title: str) -> str:
        """Extract minimal job description from card (for raw_text field)."""
        # Just return title for now - full description extraction happens in enrichment
        return f"Job Title: {title}\n\nFull job description available on detail page."

    def _element_before(self, elem1: Tag, elem2: Tag) -> bool:
        """Check if elem1 comes before elem2 in document order."""
        # Simple check: compare string positions in parent's HTML
        parent = elem1.find_parent()
        if not parent:
            return True
        parent_html = str(parent)
        try:
            pos1 = parent_html.find(str(elem1))
            pos2 = parent_html.find(str(elem2))
            return pos1 < pos2 if pos1 != -1 and pos2 != -1 else True
        except Exception:
            return True

