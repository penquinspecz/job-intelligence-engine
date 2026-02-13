"""
SignalCraft
Copyright (c) 2026 Chris Menendez.
All Rights Reserved.
See LICENSE for permitted use.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Optional

from .fetch import FetchMethod, fetch_html
from .validate import MIN_BYTES_DEFAULT, validate_snapshot_bytes


def write_snapshot(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=path.name, dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
        os.replace(tmp_path, path)
    finally:
        try:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
        except Exception:
            pass


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def refresh_snapshot(
    provider_id: str,
    url: str,
    out_path: Path,
    *,
    force: bool = False,
    timeout: float = 20.0,
    min_bytes: int = MIN_BYTES_DEFAULT,
    fetch_method: FetchMethod = "requests",
    headers: Optional[dict[str, str]] = None,
    extraction_mode: str | None = None,
    logger: Optional[logging.Logger] = None,
) -> int:
    if logger is None:
        logger = logging.getLogger(__name__)

    req_headers = dict(headers or {})
    req_headers.setdefault("User-Agent", "signalcraft/0.1 (+snapshot-refresh)")
    req_headers.setdefault("Accept", "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8")

    logger.info("Refreshing snapshot for %s from %s", provider_id, url)

    meta_path = out_path.parent / "index.fetch.json"
    try:
        html, meta = fetch_html(
            url,
            method=fetch_method,
            timeout_s=timeout,
            user_agent=req_headers.get("User-Agent"),
            headers=req_headers,
        )
    except RuntimeError as exc:
        meta = {
            "method": fetch_method,
            "url": url,
            "final_url": None,
            "status_code": None,
            "fetched_at": None,
            "bytes_len": 0,
            "error": str(exc),
        }
        _write_json(meta_path, meta)
        raise

    _write_json(meta_path, meta)

    raw_path = out_path.parent / "index.raw.html"
    if html:
        write_snapshot(raw_path, html.encode("utf-8"))

    if meta.get("error"):
        message = f"Snapshot fetch failed for {provider_id}: {meta['error']}"
        logger.error(message)
        raise RuntimeError(message)

    status_code = meta.get("status_code")
    if status_code and status_code != 200:
        reason = f"http status {status_code}"
        if not force:
            message = f"Snapshot fetch failed for {provider_id}: {reason}"
            logger.error(message)
            raise RuntimeError(message)
        logger.warning("Forcing snapshot write despite %s", reason)

    if min_bytes != MIN_BYTES_DEFAULT:
        os.environ["JOBINTEL_SNAPSHOT_MIN_BYTES"] = str(min_bytes)
    valid, reason = validate_snapshot_bytes(
        provider_id,
        html.encode("utf-8"),
        extraction_mode=extraction_mode,
    )
    if not valid and not force:
        message = f"Invalid snapshot for {provider_id} at {out_path}: {reason}"
        logger.error(message)
        raise RuntimeError(message)
    if not valid and force:
        logger.warning("Forcing snapshot write despite invalid content: %s", reason)

    write_snapshot(out_path, html.encode("utf-8"))
    size_bytes = len(html.encode("utf-8"))
    logger.info("Wrote snapshot for %s to %s (%d bytes)", provider_id, out_path, size_bytes)
    return 0
