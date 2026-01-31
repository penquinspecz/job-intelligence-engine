from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from bs4 import BeautifulSoup
    from bs4.element import Tag
except Exception:  # pragma: no cover - only used if BeautifulSoup is missing
    BeautifulSoup = None
    Tag = object

from ji_engine.models import JobSource, RawJobPosting
from ji_engine.providers.base import BaseJobProvider
from jobintel.snapshots.validate import validate_snapshot_file

_ASHBY_JOB_ID_RE = re.compile(r"/([0-9a-f-]{36})/application", re.IGNORECASE)
_NEXT_DATA_RE = re.compile(
    r'<script[^>]*id="__NEXT_DATA__"[^>]*>(?P<data>.*?)</script>',
    re.DOTALL | re.IGNORECASE,
)


def _infer_board_url(html: str) -> Optional[str]:
    match = re.search(r"https?://jobs\.ashbyhq\.com/([a-zA-Z0-9_-]+)", html)
    if not match:
        return None
    return f"https://jobs.ashbyhq.com/{match.group(1)}"


def _extract_json_after_marker(html: str, marker: str) -> Optional[str]:
    idx = html.find(marker)
    if idx == -1:
        return None
    start = html.find("{", idx)
    if start == -1:
        return None
    depth = 0
    for i in range(start, len(html)):
        ch = html[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return html[start : i + 1]
    return None


def _extract_next_data_payload(html: str) -> Optional[Any]:
    match = _NEXT_DATA_RE.search(html)
    if not match:
        return None
    data = match.group("data").strip()
    if not data:
        return None
    try:
        return json.loads(data)
    except Exception:
        return None


def _extract_app_data_payload(html: str) -> Optional[Any]:
    raw = _extract_json_after_marker(html, "window.__appData")
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def _walk_payload(node: Any, matches: List[dict], predicate) -> None:
    if isinstance(node, dict):
        if predicate(node):
            matches.append(node)
        for key in sorted(node.keys()):
            _walk_payload(node[key], matches, predicate)
    elif isinstance(node, list):
        for item in node:
            _walk_payload(item, matches, predicate)


def _extract_apply_url_from_payload(node: dict, board_url: Optional[str]) -> Optional[str]:
    for key in ("applyUrl", "apply_url", "applyURL", "applicationUrl", "applicationURL", "url", "postingUrl"):
        value = node.get(key)
        if isinstance(value, str) and "ashbyhq.com" in value and "/application" in value:
            return value
    for key in ("jobId", "job_id", "id"):
        value = node.get(key)
        if isinstance(value, str) and _ASHBY_JOB_ID_RE.search(f"/{value}/application"):
            if board_url:
                base = board_url.rstrip("/")
                return f"{base}/{value}/application"
    return None


def _extract_title_from_payload(node: dict) -> Optional[str]:
    for key in ("title", "jobTitle", "roleName", "name"):
        value = node.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _extract_location_from_payload(node: dict) -> Optional[str]:
    for key in ("location", "locationName", "jobLocation", "locationString"):
        value = node.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _extract_team_from_payload(node: dict) -> Optional[str]:
    for key in ("team", "department", "dept", "group"):
        value = node.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _derive_job_id(apply_url: str, title: str, location: Optional[str], team: Optional[str]) -> str:
    match = _ASHBY_JOB_ID_RE.search(apply_url or "")
    if match:
        return match.group(1)
    payload = "|".join([apply_url or "", title or "", location or "", team or ""]).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _stable_posting_key(job: RawJobPosting) -> tuple[str, str, str, str]:
    return (job.apply_url or "", job.title or "", job.location or "", job.team or "")


def _build_postings_from_payload(
    payload: Any,
    now: datetime,
    board_url: Optional[str],
) -> List[RawJobPosting]:
    matches: List[dict] = []

    def predicate(node: dict) -> bool:
        apply_url = _extract_apply_url_from_payload(node, board_url)
        title = _extract_title_from_payload(node)
        return bool(apply_url and title)

    _walk_payload(payload, matches, predicate)
    results: List[RawJobPosting] = []
    seen_apply_urls: set[str] = set()
    for job in matches:
        apply_url = _extract_apply_url_from_payload(job, board_url)
        title = _extract_title_from_payload(job)
        if not apply_url or not title:
            continue
        if apply_url in seen_apply_urls:
            continue
        seen_apply_urls.add(apply_url)
        location = _extract_location_from_payload(job)
        team = _extract_team_from_payload(job)
        job_id = _derive_job_id(apply_url, title, location, team)
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
    results.sort(key=_stable_posting_key)
    return results


def _parse_snapshot_jobs(html: str, now: datetime, board_url: Optional[str]) -> List[RawJobPosting]:
    payload = _extract_next_data_payload(html)
    if payload is not None:
        parsed = _build_postings_from_payload(payload, now, board_url)
        if parsed:
            return parsed

    payload = _extract_app_data_payload(html)
    if payload is not None:
        parsed = _build_postings_from_payload(payload, now, board_url)
        if parsed:
            return parsed

    return []


def parse_ashby_snapshot_html(
    html: str,
    now: Optional[datetime] = None,
    *,
    strict: bool = False,
) -> List[Dict[str, Any]]:
    """
    Deterministically parse Ashby snapshot HTML without DOM parsing.
    """
    timestamp = now or datetime.utcnow()
    board_url = _infer_board_url(html)
    jobs = _parse_snapshot_jobs(html, timestamp, board_url)
    if strict and not jobs:
        raise RuntimeError("Deterministic Ashby snapshot parse failed (no JSON payload found).")
    return [job.to_dict() for job in jobs]


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
        ok, reason = validate_snapshot_file(self.provider_id, snapshot_file)
        if not ok:
            raise RuntimeError(f"Invalid snapshot for {self.provider_id} at {snapshot_file}: {reason}")
        html = snapshot_file.read_text(encoding="utf-8")
        return self._parse_html(html)

    def _fetch_live_html(self) -> str:
        from ji_engine.providers.retry import fetch_urlopen_with_retry

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
        return fetch_urlopen_with_retry(self.board_url, headers=headers, timeout_s=20)

    def _parse_html(self, html: str) -> List[RawJobPosting]:
        now = datetime.utcnow()
        parsed = _parse_snapshot_jobs(html, now, self.board_url)
        if parsed:
            return parsed

        if os.environ.get("JOBINTEL_ALLOW_HTML_FALLBACK", "1") == "1":
            print("[AshbyProvider] WARNING: Falling back to HTML parsing; JSON payload not found.")
            return self._parse_html_fallback(html, now)

        raise RuntimeError("Deterministic Ashby snapshot parse failed (no JSON payload found).")

    def _parse_html_fallback(self, html: str, now: datetime) -> List[RawJobPosting]:
        if BeautifulSoup is None:
            raise RuntimeError(
                "BeautifulSoup is required for HTML fallback parsing. "
                "Install beautifulsoup4 or enable deterministic JSON extraction."
            )
        soup = BeautifulSoup(html, "html.parser")
        results: List[RawJobPosting] = []
        seen_apply_urls: set[str] = set()

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

        results.sort(key=_stable_posting_key)
        return results

    def _parse_next_data(self, html: str, now: datetime) -> List[RawJobPosting]:
        payload = _extract_next_data_payload(html)
        if payload is None:
            return []
        return _build_postings_from_payload(payload, now, self.board_url)

    def _parse_app_data(self, html: str, now: datetime) -> List[RawJobPosting]:
        payload = _extract_app_data_payload(html)
        if payload is None:
            return []
        return _build_postings_from_payload(payload, now, self.board_url)

    def _looks_like_job(self, node: dict[str, Any]) -> bool:
        apply_url = _extract_apply_url_from_payload(node, self.board_url)
        title = _extract_title_from_payload(node)
        return bool(apply_url and title)

    def _extract_apply_url(self, node: dict[str, Any]) -> Optional[str]:
        return _extract_apply_url_from_payload(node, self.board_url)

    def _extract_title_from_payload(self, node: dict[str, Any]) -> Optional[str]:
        return _extract_title_from_payload(node)

    def _extract_location_from_payload(self, node: dict[str, Any]) -> Optional[str]:
        return _extract_location_from_payload(node)

    def _extract_team_from_payload(self, node: dict[str, Any]) -> Optional[str]:
        return _extract_team_from_payload(node)

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
        return _derive_job_id(apply_url, title, location, team)
