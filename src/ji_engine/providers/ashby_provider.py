from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, List, Optional

from bs4 import BeautifulSoup
from bs4.element import Tag

from ji_engine.models import JobSource, RawJobPosting
from ji_engine.providers.base import BaseJobProvider
from ji_engine.providers.retry import fetch_urlopen_with_retry
from ji_engine.utils.time import utc_now_naive
from jobintel.snapshots.validate import validate_snapshot_file

_ASHBY_JOB_ID_RE = re.compile(r"/([0-9a-f-]{36})/application", re.IGNORECASE)


def parse_ashby_snapshot_html_with_source(html: str, *, strict: bool = False) -> tuple[list[dict[str, Any]], str]:
    provider = AshbyProvider("snapshot", "https://jobs.ashbyhq.com/", Path("."))
    now = utc_now_naive()
    soup = BeautifulSoup(html, "html.parser")
    parsed = provider._parse_next_data(soup, now)
    if parsed:
        return [job.to_dict() for job in parsed], "next_data"
    parsed = provider._parse_app_data(html, now)
    if parsed:
        return [job.to_dict() for job in parsed], "app_data"
    if strict:
        raise RuntimeError("Ashby snapshot JSON payload not found; HTML fallback disallowed.")
    return [], "html_fallback"


class AshbyProvider(BaseJobProvider):
    def __init__(
        self,
        provider_id: str,
        board_url: str,
        snapshot_dir: Path,
        *,
        mode: str = "SNAPSHOT",
        snapshot_write_dir: Path | None = None,
    ) -> None:
        super().__init__(mode=mode, data_dir=str(snapshot_dir.parent))
        self.provider_id = provider_id
        self.board_url = board_url
        self.snapshot_dir = snapshot_dir
        self.snapshot_write_dir = snapshot_write_dir

    def _snapshot_file(self) -> Path:
        return self.snapshot_dir / "index.html"

    def _snapshot_write_file(self) -> Path:
        if self.snapshot_write_dir is None:
            raise RuntimeError(
                "snapshot_write_dir is required for live snapshot writes; pass --snapshot-write-dir explicitly."
            )
        return Path(self.snapshot_write_dir) / "index.html"

    def scrape_live(self) -> List[RawJobPosting]:
        html = self._fetch_live_html()
        snapshot_file = self._snapshot_write_file()
        snapshot_file.parent.mkdir(parents=True, exist_ok=True)
        snapshot_file.write_text(html, encoding="utf-8")
        return self._parse_html(html)

    def load_from_snapshot(self) -> List[RawJobPosting]:
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        snapshot_file = self._snapshot_file()
        if not snapshot_file.exists():
            print(f"[AshbyProvider] ❌ Snapshot not found at {snapshot_file}")
            return []
        ok, reason = validate_snapshot_file(self.provider_id, snapshot_file)
        if not ok:
            raise RuntimeError(f"Invalid snapshot for {self.provider_id} at {snapshot_file}: {reason}")
        html = snapshot_file.read_text(encoding="utf-8")
        return self._parse_html(html)

    def _fetch_live_html(self) -> str:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": self.board_url,
            "Cache-Control": "no-cache",
        }
        return fetch_urlopen_with_retry(
            self.board_url,
            headers=headers,
            timeout_s=20,
            provider_id=self.provider_id,
        )

    def _parse_html(self, html: str) -> List[RawJobPosting]:
        soup = BeautifulSoup(html, "html.parser")
        results: List[RawJobPosting] = []
        seen_apply_urls: set[str] = set()
        now = utc_now_naive()

        parsed = self._parse_next_data(soup, now)
        if parsed:
            return parsed
        parsed = self._parse_app_data(html, now)
        if parsed:
            return parsed

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

        results.sort(key=lambda j: (j.apply_url or "", j.title or "", j.location or "", j.team or ""))
        return results

    def _parse_next_data(self, soup: BeautifulSoup, now: datetime) -> List[RawJobPosting]:
        script = soup.find("script", id="__NEXT_DATA__", type="application/json")
        if not script or not script.string:
            return []
        try:
            payload = json.loads(script.string)
        except Exception:
            return []
        matches: List[dict[str, Any]] = []

        def walk(node: Any) -> None:
            if isinstance(node, dict):
                if self._looks_like_job(node):
                    matches.append(node)
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for item in node:
                    walk(item)

        walk(payload)
        results: List[RawJobPosting] = []
        seen_apply_urls: set[str] = set()
        for job in matches:
            apply_url = self._extract_apply_url(job)
            title = self._extract_title_from_payload(job)
            if not apply_url or not title:
                continue
            if apply_url in seen_apply_urls:
                continue
            seen_apply_urls.add(apply_url)
            location = self._extract_location_from_payload(job)
            team = self._extract_team_from_payload(job)
            job_id = self._extract_job_id(apply_url, title, location, team)
            results.append(
                RawJobPosting(
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
            )
        results.sort(key=lambda j: (j.apply_url or "", j.title or "", j.location or "", j.team or ""))
        return results

    def _parse_app_data(self, html: str, now: datetime) -> List[RawJobPosting]:
        marker = "window.__appData"
        idx = html.find(marker)
        if idx == -1:
            return []
        start = html.find("{", idx)
        if start == -1:
            return []
        depth = 0
        end = None
        for i in range(start, len(html)):
            ch = html[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        if end is None:
            return []
        try:
            payload = json.loads(html[start:end])
        except Exception:
            return []
        matches: List[dict[str, Any]] = []

        def walk(node: Any) -> None:
            if isinstance(node, dict):
                if self._looks_like_job(node):
                    matches.append(node)
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for item in node:
                    walk(item)

        walk(payload)
        results: List[RawJobPosting] = []
        seen_apply_urls: set[str] = set()
        for job in matches:
            apply_url = self._extract_apply_url(job)
            title = self._extract_title_from_payload(job)
            if not apply_url or not title:
                continue
            if apply_url in seen_apply_urls:
                continue
            seen_apply_urls.add(apply_url)
            location = self._extract_location_from_payload(job)
            team = self._extract_team_from_payload(job)
            job_id = self._extract_job_id(apply_url, title, location, team)
            results.append(
                RawJobPosting(
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
            )
        results.sort(key=lambda j: (j.apply_url or "", j.title or "", j.location or "", j.team or ""))
        return results

    def _looks_like_job(self, node: dict[str, Any]) -> bool:
        apply_url = self._extract_apply_url(node)
        title = self._extract_title_from_payload(node)
        return bool(apply_url and title)

    def _extract_apply_url(self, node: dict[str, Any]) -> Optional[str]:
        for key in ("applyUrl", "apply_url", "applyURL", "applicationUrl", "applicationURL", "url", "postingUrl"):
            value = node.get(key)
            if isinstance(value, str) and "ashbyhq.com" in value and "/application" in value:
                return value
        for key in ("jobId", "job_id", "id"):
            value = node.get(key)
            if isinstance(value, str) and _ASHBY_JOB_ID_RE.search(f"/{value}/application"):
                base = self.board_url.rstrip("/")
                return f"{base}/{value}/application"
        return None

    def _extract_title_from_payload(self, node: dict[str, Any]) -> Optional[str]:
        for key in ("title", "jobTitle", "roleName", "name"):
            value = node.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    def _extract_location_from_payload(self, node: dict[str, Any]) -> Optional[str]:
        for key in ("location", "locationName", "jobLocation", "locationString"):
            value = node.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    def _extract_team_from_payload(self, node: dict[str, Any]) -> Optional[str]:
        for key in ("team", "department", "dept", "group"):
            value = node.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

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
        payload = "|".join([apply_url or "", title or "", location or "", team or ""]).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()
