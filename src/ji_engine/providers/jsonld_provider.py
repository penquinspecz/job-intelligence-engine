"""
SignalCraft
Copyright (c) 2026 Chris Menendez.
All Rights Reserved.
See LICENSE for permitted use.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List

from bs4 import BeautifulSoup

from ji_engine.models import JobSource, RawJobPosting
from ji_engine.providers.base import BaseJobProvider
from ji_engine.providers.llm_fallback import load_cached_llm_fallback
from ji_engine.providers.retry import fetch_text_with_retry
from ji_engine.utils.job_identity import job_identity
from ji_engine.utils.time import utc_now_naive
from jobintel.snapshots.validate import validate_snapshot_file


class JsonLdProvider(BaseJobProvider):
    """Deterministic provider for pages exposing JobPosting JSON-LD."""

    def __init__(
        self,
        provider_id: str,
        careers_url: str,
        snapshot_dir: Path,
        *,
        mode: str = "SNAPSHOT",
        snapshot_write_dir: Path | None = None,
        llm_fallback: dict | None = None,
    ) -> None:
        super().__init__(mode=mode, data_dir=str(snapshot_dir.parent))
        self.provider_id = provider_id
        self.careers_url = careers_url
        self.snapshot_dir = snapshot_dir
        self.snapshot_write_dir = snapshot_write_dir
        self.llm_fallback = llm_fallback or {"enabled": False}

    def _snapshot_file(self) -> Path:
        return self.snapshot_dir / "index.html"

    def _snapshot_write_file(self) -> Path:
        if self.snapshot_write_dir is None:
            raise RuntimeError("snapshot_write_dir is required for live snapshot writes.")
        return Path(self.snapshot_write_dir) / "index.html"

    def scrape_live(self) -> List[RawJobPosting]:
        html = fetch_text_with_retry(self.careers_url, provider_id=self.provider_id)
        snapshot_file = self._snapshot_write_file()
        snapshot_file.parent.mkdir(parents=True, exist_ok=True)
        snapshot_file.write_text(html, encoding="utf-8")
        now = utc_now_naive().replace(microsecond=0)
        return self._parse_html(html, now=now)

    def load_from_snapshot(self) -> List[RawJobPosting]:
        snapshot_file = self._snapshot_file()
        if not snapshot_file.exists():
            return []
        ok, reason = validate_snapshot_file(self.provider_id, snapshot_file, extraction_mode="jsonld")
        if not ok:
            raise RuntimeError(f"Invalid snapshot for {self.provider_id} at {snapshot_file}: {reason}")
        html = snapshot_file.read_text(encoding="utf-8")
        now = datetime.fromtimestamp(snapshot_file.stat().st_mtime, tz=timezone.utc).replace(microsecond=0)
        return self._parse_html(html, now=now.replace(tzinfo=None))

    def _parse_html(self, html: str, *, now: datetime) -> List[RawJobPosting]:
        soup = BeautifulSoup(html, "html.parser")
        payloads: list[dict[str, Any]] = []
        for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
            text = script.string or script.get_text()
            if not text:
                continue
            try:
                data = json.loads(text)
            except Exception:
                continue
            self._walk(data, payloads)

        seen_urls: set[str] = set()
        postings: list[RawJobPosting] = []
        for payload in payloads:
            apply_url = str(payload.get("url") or "").strip()
            title = str(payload.get("title") or payload.get("name") or "").strip()
            if not apply_url or not title:
                continue
            if apply_url in seen_urls:
                continue
            seen_urls.add(apply_url)
            location = self._extract_location(payload.get("jobLocation"))
            team = self._extract_org(payload.get("hiringOrganization"))
            identity_seed = {
                "title": title,
                "location": location,
                "team": team,
                "apply_url": apply_url,
            }
            postings.append(
                RawJobPosting(
                    source=JobSource.ASHBY,
                    title=title,
                    location=location,
                    team=team,
                    apply_url=apply_url,
                    detail_url=apply_url,
                    raw_text="",
                    scraped_at=now,
                    job_id=job_identity(identity_seed, mode="provider"),
                )
            )
        postings.sort(key=lambda item: ((item.apply_url or "").lower(), (item.title or "").lower()))
        if postings:
            return postings
        if self.llm_fallback.get("enabled"):
            raw_cache_dir = str(self.llm_fallback.get("cache_dir") or "").strip()
            if not raw_cache_dir:
                raise RuntimeError("LLM fallback enabled but cache_dir not configured")
            cache_dir = Path(raw_cache_dir).expanduser()
            return load_cached_llm_fallback(
                html,
                provider_id=self.provider_id,
                cache_dir=cache_dir,
                now=now,
            )
        return postings

    def _walk(self, node: Any, sink: list[dict[str, Any]]) -> None:
        if isinstance(node, list):
            for item in node:
                self._walk(item, sink)
            return
        if not isinstance(node, dict):
            return
        node_type = str(node.get("@type") or "").strip().lower()
        if node_type == "jobposting":
            sink.append(node)
        for value in node.values():
            self._walk(value, sink)

    def _extract_location(self, value: Any) -> str | None:
        if isinstance(value, str):
            text = value.strip()
            return text or None
        if isinstance(value, list):
            for item in value:
                parsed = self._extract_location(item)
                if parsed:
                    return parsed
            return None
        if not isinstance(value, dict):
            return None
        address = value.get("address")
        if isinstance(address, dict):
            parts = [
                str(address.get("addressLocality") or "").strip(),
                str(address.get("addressRegion") or "").strip(),
                str(address.get("addressCountry") or "").strip(),
            ]
            joined = ", ".join([part for part in parts if part])
            return joined or None
        name = str(value.get("name") or "").strip()
        return name or None

    def _extract_org(self, value: Any) -> str | None:
        if isinstance(value, str):
            text = value.strip()
            return text or None
        if isinstance(value, dict):
            name = str(value.get("name") or "").strip()
            return name or None
        return None
