#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ji_engine.providers.openai_provider import CAREERS_SEARCH_URL
from ji_engine.providers.registry import load_providers_config


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> Optional[str]:
    if not path.exists():
        return None
    try:
        return _sha256_bytes(path.read_bytes())
    except Exception:
        return None


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=path.name, dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp_path, path)
    finally:
        try:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
        except Exception:
            pass


def _meta_path(out_dir: Path) -> Path:
    return out_dir / "index.meta.json"


def _build_meta(
    *,
    provider: str,
    url: str,
    http_status: Optional[int],
    bytes_count: int,
    sha256: Optional[str],
    note: Optional[str],
) -> dict:
    return {
        "fetched_at": _utcnow_iso(),
        "url": url,
        "http_status": http_status,
        "bytes": bytes_count,
        "sha256": sha256,
        "provider": provider,
        "note": note,
    }


def _write_meta(out_dir: Path, payload: dict) -> None:
    _atomic_write(_meta_path(out_dir), json.dumps(payload, indent=2, sort_keys=True).encode("utf-8"))


def _fetch_html(url: str, timeout: float, user_agent: str) -> Tuple[Optional[bytes], Optional[int], Optional[str]]:
    req = Request(url, headers={"User-Agent": user_agent})
    try:
        with urlopen(req, timeout=timeout) as resp:
            data = resp.read()
            return data, getattr(resp, "status", 200), None
    except HTTPError as e:
        try:
            body = e.read()
        except Exception:
            body = None
        return body, e.code, f"HTTPError: {e}"
    except URLError as e:
        return None, None, f"URLError: {e}"


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", required=True)
    ap.add_argument("--url")
    ap.add_argument("--out_dir")
    ap.add_argument("--timeout", type=float, default=20.0)
    ap.add_argument("--user_agent", default="job-intelligence-engine/0.1")
    ap.add_argument("--dry_run", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument(
        "--providers_config",
        default=str(Path("config") / "providers.json"),
        help="Path to providers config JSON.",
    )
    args = ap.parse_args(argv)

    provider = args.provider.lower().strip()
    providers = load_providers_config(Path(args.providers_config))
    provider_map = {p["provider_id"]: p for p in providers}

    if provider not in provider_map and provider != "openai":
        raise SystemExit(f"Unknown provider '{args.provider}'.")

    provider_cfg = provider_map.get(provider)
    url = args.url or (provider_cfg.get("board_url") if provider_cfg else None) or CAREERS_SEARCH_URL
    out_dir = Path(
        args.out_dir
        or (provider_cfg.get("snapshot_dir") if provider_cfg else None)
        or str(Path("data") / f"{provider}_snapshots")
    )
    html_path = out_dir / "index.html"

    data, status, error = _fetch_html(url, args.timeout, args.user_agent)
    ok = status == 200 and data is not None
    note = None
    if not ok:
        note = error or f"HTTP status {status}"
    if not ok and not args.force:
        if not args.dry_run:
            payload = _build_meta(
                provider=provider,
                url=url,
                http_status=status,
                bytes_count=len(data or b""),
                sha256=_sha256_file(html_path),
                note=note,
            )
            _write_meta(out_dir, payload)
        return 0 if args.dry_run else 1

    if args.dry_run:
        return 0 if ok else 1

    _atomic_write(html_path, data or b"")
    sha256 = _sha256_file(html_path)
    payload = _build_meta(
        provider=provider,
        url=url,
        http_status=status,
        bytes_count=len(data or b""),
        sha256=sha256,
        note=note,
    )
    _write_meta(out_dir, payload)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
