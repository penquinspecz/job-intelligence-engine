from __future__ import annotations

import hashlib
import re
from datetime import datetime
from pathlib import Path
from typing import List, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup
from bs4.element import Tag

from ji_engine.models import JobSource, RawJobPosting
from ji_engine.providers.base import BaseJobProvider

_ASHBY_JOB_ID_RE = re.compile(r"/([0-9a-f-]{36})/application", re.IGNORECASE)


class AshbyProvider(BaseJobProvider):
    def __init__(
        self,
        provider_id: str,
        board_url: str,
        snapshot_dir: Path,
        *,
        mode: str = "SNAPSHOT",
    ) -> None:
        super().__init__(mode=mode, data_dir=str(snapshot_dir.parent))
        self.provider_id = provider_id
        self.board_url = board_url
        self.snapshot_dir = snapshot_dir

    def _snapshot_file(self) -> Path:
        return self.snapshot_dir / "index.html"

    def scrape_live(self) -> List[RawJobPosting]:
        html = self._fetch_live_html()
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        self._snapshot_file().write_text(html, encoding="utf-8")
        return self._parse_html(html)

    def load_from_snapshot(self) -> List[RawJobPosting]:
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        snapshot_file = self._snapshot_file()
        if not snapshot_file.exists():
            print(f"[AshbyProvider] ❌ Snapshot not found at {snapshot_file}")
            return []
        html = snapshot_file.read_text(encoding="utf-8")
        return self._parse_html(html)

    def _fetch_live_html(self) -> str:
        req = Request(self.board_url, headers={"User-Agent": "job-intelligence-engine/0.1"})
        try:
            with urlopen(req, timeout=20) as resp:
                status = getattr(resp, "status", 200)
                if status != 200:
                    raise RuntimeError(f"Live scrape failed with status {status} at {self.board_url}")
                return resp.read().decode("utf-8")
        except HTTPError as e:
            raise RuntimeError(f"Live scrape failed with status {e.code} at {self.board_url}") from e
        except URLError as e:
            raise RuntimeError(f"Live scrape failed with error {e}") from e

    def _parse_html(self, html: str) -> List[RawJobPosting]:
        soup = BeautifulSoup(html, "html.parser")
        results: List[RawJobPosting] = []
        seen_apply_urls: set[str] = set()
        now = datetime.utcnow()

        anchors = soup.find_all("a", href=lambda h: h and "ashbyhq.com" in h and "/application" in h)
        for anchor in anchors:
            if not isinstance(anchor, Tag):
                continue
            apply_url = (anchor.get("href") or "").strip()
            if not apply_url or apply_url in seen_apply_urls:
                continue
            seen_apply_urls.add(apply_url)

            card = anchor.find_parent(["li", "div", "article", "section", "tr"]) or anchor.parent
            title = self._extract_title(card, anchor)
            location = self._extract_field(card, ["location", "loc", "city", "office"])
            team = self._extract_field(card, ["team", "department", "dept", "group"])
            job_id = self._extract_job_id(apply_url, title, location, team)

            posting = RawJobPosting(
                source=JobSource.ASHBY,
                title=title,
                location=location,
                team=team,
                apply_url=apply_url,
                detail_url=None,
                raw_text="",
                scraped_at=now,
                job_id=job_id,
            )
            results.append(posting)

        return results

    def _extract_title(self, card: Tag, anchor: Tag) -> str:
        if isinstance(card, Tag):
            for elem in card.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
                text = elem.get_text(strip=True)
                if text:
                    return text
            for elem in card.find_all(attrs={"data-testid": lambda v: v and "title" in v.lower()}):
                text = elem.get_text(strip=True)
                if text:
                    return text
            for elem in card.find_all(class_=lambda c: c and "title" in " ".join(c).lower()):
                text = elem.get_text(strip=True)
                if text:
                    return text
        text = anchor.get_text(strip=True)
        return text if text else "Untitled Position"

    def _extract_field(self, card: Tag, keywords: List[str]) -> Optional[str]:
        if not isinstance(card, Tag):
            return None
        for elem in card.find_all(["span", "div", "p"]):
            class_attr = " ".join(elem.get("class", [])).lower()
            if any(k in class_attr for k in keywords):
                text = elem.get_text(strip=True)
                return text if text else None
        for elem in card.find_all(["span", "div", "p"]):
            text = elem.get_text(strip=True)
            if not text:
                continue
            lowered = text.lower()
            for prefix in ["location:", "team:", "department:", "dept:", "group:"]:
                if lowered.startswith(prefix):
                    return text[len(prefix) :].strip() or None
        return None

    def _extract_job_id(self, apply_url: str, title: str, location: Optional[str], team: Optional[str]) -> str:
        match = _ASHBY_JOB_ID_RE.search(apply_url or "")
        if match:
            return match.group(1)
        payload = "|".join([title or "", location or "", team or ""]).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()
