#!/usr/bin/env python3
from __future__ import annotations
try:
    import _bootstrap  # type: ignore
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

import argparse
import hashlib
import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from ji_engine.config import DATA_DIR, RAW_JOBS_JSON
from ji_engine.providers.openai_provider import OpenAICareersProvider
from ji_engine.providers.ashby_provider import AshbyProvider
from ji_engine.providers.registry import load_providers_config
from ji_engine.providers.snapshot_json_provider import SnapshotJsonProvider

_STATUS_CODE_RE = re.compile(r"status (\d+)")

logger = logging.getLogger(__name__)


def _sort_key(job: Dict[str, Any]) -> tuple[str, str]:
    url = str(job.get("apply_url") or job.get("detail_url") or "").lower()
    title = str(job.get("title") or "").lower()
    return (url, title)


def _normalize_jobs(raw: List[Any]) -> List[Dict[str, Any]]:
    jobs: List[Dict[str, Any]] = []
    for item in raw:
        if hasattr(item, "to_dict"):
            jobs.append(item.to_dict())
        elif isinstance(item, dict):
            jobs.append(item)
    return sorted(jobs, key=_sort_key)


def _write_raw_jobs(provider_id: str, jobs: List[Dict[str, Any]], output_dir: Path) -> Path:
    filename = f"{provider_id}_raw_jobs.json"
    out_path = output_dir / filename
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(jobs, f, indent=2, ensure_ascii=False)
    print(f"Scraped {len(jobs)} jobs.")
    print(f"Wrote JSON to {out_path.resolve()}")
    return out_path


def _sha256(path: Path) -> Optional[str]:
    if not path.exists():
        return None
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except Exception:
        return None


def _scrape_meta_path(provider_id: str, output_dir: Path) -> Path:
    return output_dir / f"{provider_id}_scrape_meta.json"


def _snapshot_meta_path(snapshot_path: Path) -> Path:
    return snapshot_path.with_suffix(".meta.json")


def _load_snapshot_meta(snapshot_path: Path) -> Dict[str, Any]:
    meta_path = _snapshot_meta_path(snapshot_path)
    if not meta_path.exists():
        return {}
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _write_scrape_meta(provider_id: str, output_dir: Path, meta: Dict[str, Any]) -> None:
    path = _scrape_meta_path(provider_id, output_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(meta)
    payload["provider"] = provider_id
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")


def _parse_status_code(error: str) -> Optional[int]:
    match = _STATUS_CODE_RE.search(error or "")
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def main(argv: List[str] | None = None) -> int:
    if not logging.getLogger().hasHandlers():
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    ap = argparse.ArgumentParser()
    ap.add_argument("--providers", default="openai", help="Comma-separated provider ids.")
    ap.add_argument(
        "--mode",
        choices=["SNAPSHOT", "LIVE", "AUTO"],
        default=os.getenv("CAREERS_MODE"),
        help="Scrape mode override. Default from CAREERS_MODE env var when set.",
    )
    ap.add_argument(
        "--providers-config",
        default=str(Path("config") / "providers.json"),
        help="Path to providers config JSON.",
    )
    args = ap.parse_args(argv or [])

    providers = load_providers_config(Path(args.providers_config))
    provider_map = {p["provider_id"]: p for p in providers}
    requested = [p.strip() for p in args.providers.split(",") if p.strip()]
    for provider_id in requested:
        if provider_id not in provider_map:
            raise SystemExit(f"Unknown provider_id '{provider_id}' in --providers")

    output_dir = Path(DATA_DIR)
    for provider_id in requested:
        provider_cfg = provider_map[provider_id]
        mode = (args.mode or provider_cfg.get("mode") or "snapshot").upper()
        provenance: Dict[str, Any] = {
            "scrape_mode": None,
            "live_status_code": None,
            "error": None,
            "snapshot_path": None,
            "snapshot_sha256": None,
            "parsed_job_count": 0,
        }

        if provider_id == "openai":
            if mode == "AUTO":
                mode = "LIVE"
            provider = OpenAICareersProvider(mode=mode, data_dir=str(output_dir))
            snapshot_path = provider._snapshot_file()
            snapshot_meta = _load_snapshot_meta(snapshot_path)
            if mode == "LIVE":
                try:
                    raw_jobs = provider.scrape_live()
                    provenance["scrape_mode"] = "live"
                except Exception as e:
                    err = str(e)
                    provenance["live_status_code"] = _parse_status_code(err)
                    provenance["error"] = err
                    logger.warning(f"[run_scrape] LIVE failed ({e!r}) → falling back to SNAPSHOT")
                    provider = OpenAICareersProvider(mode="SNAPSHOT", data_dir=str(output_dir))
                    raw_jobs = provider.load_from_snapshot()
                    provenance["scrape_mode"] = "snapshot"
            else:
                raw_jobs = provider.fetch_jobs()
                provenance["scrape_mode"] = "snapshot"
            provenance["snapshot_path"] = str(snapshot_path)
            provenance["snapshot_sha256"] = snapshot_meta.get("sha256") or _sha256(snapshot_path)
            if snapshot_meta.get("fetched_at"):
                provenance["fetched_at"] = snapshot_meta.get("fetched_at")
            jobs = _normalize_jobs(raw_jobs)
            _write_raw_jobs(provider_id, jobs, output_dir)
            provenance["parsed_job_count"] = len(jobs)
            _write_scrape_meta(provider_id, output_dir, provenance)
            # For backward compatibility, also write to canonical RAW_JOBS_JSON.
            if provider_id == "openai":
                RAW_JOBS_JSON.write_text(json.dumps(jobs, indent=2, ensure_ascii=False), encoding="utf-8")
        else:
            provider_type = provider_cfg.get("type", "snapshot")
            if provider_type == "ashby":
                if mode == "AUTO":
                    mode = "LIVE" if provider_cfg.get("live_enabled", True) else "SNAPSHOT"
                snapshot_dir = Path(provider_cfg["snapshot_dir"])
                snapshot_path = Path(provider_cfg["snapshot_path"])
                if mode == "SNAPSHOT" and not snapshot_path.exists():
                    msg = (
                        f"Snapshot not found at {snapshot_path} for provider {provider_id}. "
                        "Add a snapshot file or update providers config."
                    )
                    logger.error(msg)
                    raise SystemExit(2)
                provider = AshbyProvider(
                    provider_id=provider_id,
                    board_url=provider_cfg["board_url"],
                    snapshot_dir=snapshot_dir,
                    mode=mode,
                )
                if mode == "LIVE":
                    try:
                        raw_jobs = provider.scrape_live()
                        provenance["scrape_mode"] = "live"
                    except Exception as e:
                        err = str(e)
                        provenance["live_status_code"] = _parse_status_code(err)
                        provenance["error"] = err
                        logger.warning(f"[run_scrape] LIVE failed ({e!r}) → falling back to SNAPSHOT")
                        if not snapshot_path.exists():
                            msg = (
                                f"Snapshot not found at {snapshot_path} for provider {provider_id}. "
                                "Add a snapshot file or update providers config."
                            )
                            logger.error(msg)
                            raise SystemExit(2)
                        raw_jobs = provider.load_from_snapshot()
                        provenance["scrape_mode"] = "snapshot"
                else:
                    raw_jobs = provider.load_from_snapshot()
                    provenance["scrape_mode"] = "snapshot"
                jobs = _normalize_jobs(raw_jobs)
                _write_raw_jobs(provider_id, jobs, output_dir)
                snapshot_meta = _load_snapshot_meta(snapshot_path)
                provenance.update(
                    {
                        "snapshot_path": str(snapshot_path),
                        "snapshot_sha256": snapshot_meta.get("sha256") or _sha256(snapshot_path),
                        "parsed_job_count": len(jobs),
                    }
                )
                if snapshot_meta.get("fetched_at"):
                    provenance["fetched_at"] = snapshot_meta.get("fetched_at")
                _write_scrape_meta(provider_id, output_dir, provenance)
            else:
                if mode == "AUTO":
                    mode = "SNAPSHOT"
                if mode != "SNAPSHOT":
                    raise SystemExit(f"Provider {provider_id} supports SNAPSHOT mode only")
                snapshot_path = Path(provider_cfg["snapshot_path"])
                if not snapshot_path.exists():
                    msg = (
                        f"Snapshot not found at {snapshot_path} for provider {provider_id}. "
                        "Add a snapshot file or update providers config."
                    )
                    logger.error(msg)
                    raise SystemExit(2)
                provider = SnapshotJsonProvider(snapshot_path)
                jobs = _normalize_jobs(provider.fetch_jobs())
                _write_raw_jobs(provider_id, jobs, output_dir)
                snapshot_meta = _load_snapshot_meta(snapshot_path)
                provenance.update(
                    {
                        "scrape_mode": "snapshot",
                        "snapshot_path": str(snapshot_path),
                        "snapshot_sha256": snapshot_meta.get("sha256") or _sha256(snapshot_path),
                        "parsed_job_count": len(jobs),
                    }
                )
                if snapshot_meta.get("fetched_at"):
                    provenance["fetched_at"] = snapshot_meta.get("fetched_at")
                _write_scrape_meta(provider_id, output_dir, provenance)

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
