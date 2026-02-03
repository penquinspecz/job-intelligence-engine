from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from bs4 import BeautifulSoup
from bs4.element import Tag

from ji_engine.config import SNAPSHOT_DIR
from ji_engine.models import JobSource, RawJobPosting
from ji_engine.providers.base import BaseJobProvider
from ji_engine.providers.retry import fetch_text_with_retry
from jobintel.snapshots.validate import validate_snapshot_file

CAREERS_SEARCH_URL = "https://openai.com/careers/search/"


def _is_pinned_snapshot(snapshot_file: Path) -> bool:
    repo_data_dir = Path(__file__).resolve().parents[2] / "data"
    try:
        in_repo_data = snapshot_file.resolve().is_relative_to(repo_data_dir.resolve())
    except AttributeError:
        in_repo_data = str(snapshot_file.resolve()).startswith(str(repo_data_dir.resolve()))
    if not in_repo_data:
        return False
    return snapshot_file.parent.name.endswith("_snapshots")


def _assert_pinned_snapshot_write_allowed(snapshot_file: Path) -> None:
    if os.environ.get("PYTEST_CURRENT_TEST") and _is_pinned_snapshot(snapshot_file):
        if os.environ.get("ALLOW_SNAPSHOT_CHANGES", "0") != "1":
            raise RuntimeError(
                "Refusing to overwrite pinned snapshot fixture. "
                "Set ALLOW_SNAPSHOT_CHANGES=1 to allow intentional refresh."
            )


class OpenAICareersProvider(BaseJobProvider):
    """
    Provider for OpenAI careers (deprecated; prefer Ashby board scraping).

    For now we prioritize SNAPSHOT mode because the live site returns 403
    to our requests client. Live scraping is a best-effort bonus.

    In SNAPSHOT mode, we expect:
      data/openai_snapshots/index.html
    """

    def _snapshot_file(self) -> Path:
        # Use centralized config path
        return SNAPSHOT_DIR / "index.html"

    def fetch_jobs(self) -> List[RawJobPosting]:
        """
        Use snapshot mode when requested; in LIVE mode fetch HTML, persist a
        snapshot, then parse.
        """
        if self.mode == "SNAPSHOT":
            if os.environ.get("JOBINTEL_PROVENANCE_LOG", "0") != "1":
                snapshot_path = self._snapshot_file()
                mtime = snapshot_path.stat().st_mtime if snapshot_path.exists() else None
                print(f"[OpenAICareersProvider] MODE=SNAPSHOT path={snapshot_path} mtime={mtime}")
            return self.load_from_snapshot()

        # LIVE path: best effort fetch, then persist snapshot for reuse
        try:
            html = self._fetch_live_html()
        except Exception as e:
            if os.environ.get("JOBINTEL_PROVENANCE_LOG", "0") != "1":
                print(f"[OpenAICareersProvider] MODE=LIVE failed reason={e!r} -> SNAPSHOT")
            print(f"[OpenAICareersProvider] LIVE blocked ({e}). Using snapshot.")
            return self.load_from_snapshot()

        SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
        _assert_pinned_snapshot_write_allowed(self._snapshot_file())
        self._snapshot_file().write_text(html, encoding="utf-8")
        if os.environ.get("JOBINTEL_PROVENANCE_LOG", "0") != "1":
            print(
                "[OpenAICareersProvider] MODE=LIVE fetched_bytes=%d wrote_snapshot=%s"
                % (len(html.encode("utf-8")), self._snapshot_file())
            )
        return self._parse_html(html)

    def scrape_live(self) -> List[RawJobPosting]:
        """Attempt a live HTTP scrape, saving the HTML snapshot for reuse."""
        html = self._fetch_live_html()
        SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
        _assert_pinned_snapshot_write_allowed(self._snapshot_file())
        self._snapshot_file().write_text(html, encoding="utf-8")
        return self._parse_html(html)

    def load_from_snapshot(self) -> List[RawJobPosting]:
        SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
        snapshot_file = self._snapshot_file()

        if not snapshot_file.exists():
            print(f"[OpenAICareersProvider] ❌ Snapshot not found at {snapshot_file}")
            print("Save https://openai.com/careers/search/ as 'index.html' in data/openai_snapshots/ and rerun.")
            return []

        ok, reason = validate_snapshot_file("openai", snapshot_file)
        if not ok:
            raise RuntimeError(f"Invalid snapshot for openai at {snapshot_file}: {reason}")

        print(f"[OpenAICareersProvider] 📂 Using snapshot {snapshot_file}")
        html = snapshot_file.read_text(encoding="utf-8")
        return self._parse_html(html)

    def _fetch_live_html(self) -> str:
        """Fetch the careers page HTML from the live site."""
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": CAREERS_SEARCH_URL,
            "Cache-Control": "no-cache",
        }
        return fetch_text_with_retry(
            CAREERS_SEARCH_URL,
            headers=headers,
            timeout_s=20,
        )

    # ---------- Core HTML parsing ----------

    def _parse_html(self, html: str) -> List[RawJobPosting]:
        """
        Parse the saved careers page HTML using DOM targeting.
        """
        soup = BeautifulSoup(html, "html.parser")
        results: List[RawJobPosting] = []
        seen_apply_urls: set[str] = set()
        now = datetime.utcnow()

        job_cards = soup.find_all(
            ["li", "div", "article", "section"],
            class_=lambda c: (
                c and any(keyword in c.lower() for keyword in ["job", "card", "posting", "position", "role", "listing"])
            ),
        )

        if not job_cards:
            apply_links = soup.find_all("a", href=lambda h: h and "jobs.ashbyhq.com/openai/" in h)
            for link in apply_links:
                if not isinstance(link, Tag):
                    continue
                card = link.find_parent(["li", "div", "article", "section", "tr"])
                if card and card not in job_cards:
                    job_cards.append(card)

        for card in job_cards:
            if not isinstance(card, Tag):
                continue

            apply_link = card.find("a", href=lambda h: h and "jobs.ashbyhq.com/openai/" in h)
            if not apply_link or not isinstance(apply_link, Tag):
                continue

            apply_url = apply_link.get("href", "").strip()
            if not apply_url or apply_url in seen_apply_urls:
                continue
            seen_apply_urls.add(apply_url)

            raw_title = self._extract_title_from_card(card, apply_link)
            team = self._extract_team_from_card(card)
            location = self._extract_location_from_card(card)

            title = self._sanitize_title(raw_title, team, location) or raw_title or "Untitled Position"
            detail_url = self._extract_detail_url_from_card(card, apply_url)
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

        results.sort(key=self._stable_posting_key)
        print(f"[OpenAICareersProvider] Parsed {len(results)} jobs from HTML")
        return results

    # ---------- Helpers ----------

    def _extract_title_from_card(self, card: Tag, apply_link: Tag) -> str:
        title_el = card.find(attrs={"data-testid": lambda v: v and "title" in v.lower()})
        if isinstance(title_el, Tag):
            text = title_el.get_text(strip=True)
            if text:
                return text

        for heading in card.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
            if heading.get_text(strip=True) and self._element_before(heading, apply_link):
                t = heading.get_text(strip=True)
                if t and t.lower() not in ["apply", "apply now", "view job"]:
                    return t

        for anchor in card.find_all("a"):
            if anchor is apply_link:
                continue
            href = anchor.get("href", "")
            if "jobs.ashbyhq.com" in href:
                continue
            if self._element_before(anchor, apply_link):
                t = anchor.get_text(strip=True)
                if t and len(t) > 3:
                    return t

        for strong in card.find_all(["strong", "b"]):
            if self._element_before(strong, apply_link):
                t = strong.get_text(strip=True)
                if t and len(t) > 3:
                    return t

        apply_text = apply_link.get_text(strip=True)
        if apply_text and len(apply_text) > 10:
            return apply_text

        return "Untitled Position"

    def _sanitize_title(self, title: str, team: Optional[str], location: Optional[str]) -> str:
        if not title:
            return title

        sanitized = title

        def strip_suffix(text: str, suffix: str) -> str:
            return text[: -len(suffix)].strip() if suffix and text.endswith(suffix) else text

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
        for elem in card.find_all(["span", "div", "p"]):
            class_attr = elem.get("class", [])
            class_str = " ".join(class_attr).lower() if class_attr else ""
            if any(k in class_str for k in ["team", "department", "dept", "group"]):
                text = elem.get_text(strip=True)
                if text and len(text) < 100:
                    for prefix in ["team:", "department:", "dept:", "group:"]:
                        if text.lower().startswith(prefix):
                            return text[len(prefix) :].strip()
                    return text

        for elem in card.find_all(["span", "div", "p"]):
            text = elem.get_text(strip=True)
            if not text:
                continue
            lower = text.lower()
            for pattern in ["team:", "department:", "dept:"]:
                if pattern in lower:
                    parts = text.split(":", 1)
                    if len(parts) == 2:
                        team = parts[1].strip()
                        if team and len(team) < 100:
                            return team
        return None

    def _extract_location_from_card(self, card: Tag) -> Optional[str]:
        for elem in card.find_all(["span", "div", "p"]):
            class_attr = elem.get("class", [])
            class_str = " ".join(class_attr).lower() if class_attr else ""
            if any(k in class_str for k in ["location", "loc", "city", "office", "place"]):
                text = elem.get_text(strip=True)
                if text and len(text) < 100:
                    for prefix in ["location:", "loc:", "city:", "office:"]:
                        if text.lower().startswith(prefix):
                            return text[len(prefix) :].strip()
                    return text

        for elem in card.find_all(["span", "div", "p"]):
            text = elem.get_text(strip=True)
            if not text:
                continue
            lower = text.lower()
            for pattern in ["location:", "loc:", "based in:"]:
                if pattern in lower:
                    parts = text.split(":", 1)
                    if len(parts) == 2:
                        loc = parts[1].strip()
                        if loc and len(loc) < 100:
                            return loc
        return None

    def _extract_detail_url_from_card(self, card: Tag, apply_url: str) -> Optional[str]:
        for anchor in card.find_all("a"):
            href = anchor.get("href", "")
            if href and href != apply_url and "jobs.ashbyhq.com" not in href:
                return href
        return None

    def _extract_job_description_from_card(self, card: Tag, title: str) -> str:
        return f"Job Title: {title}\n\nFull job description available on detail page."

    def _stable_posting_key(self, job: RawJobPosting) -> tuple[str, str, str, str]:
        return (job.apply_url or "", job.title or "", job.location or "", job.team or "")

    def _element_before(self, elem1: Tag, elem2: Tag) -> bool:
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
