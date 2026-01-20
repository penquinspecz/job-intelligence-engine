#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

from ji_engine.config import DATA_DIR, RAW_JOBS_JSON
from ji_engine.providers.openai_provider import OpenAICareersProvider
from ji_engine.providers.registry import load_providers_config
from ji_engine.providers.snapshot_json_provider import SnapshotJsonProvider

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

        if provider_id == "openai":
            if mode == "AUTO":
                mode = "LIVE"
            provider = OpenAICareersProvider(mode=mode, data_dir=str(output_dir))
            try:
                raw_jobs = provider.fetch_jobs()
            except Exception as e:
                if mode == "LIVE":
                    logger.warning(f"[run_scrape] LIVE failed ({e!r}) → falling back to SNAPSHOT")
                    provider = OpenAICareersProvider(mode="SNAPSHOT", data_dir=str(output_dir))
                    raw_jobs = provider.fetch_jobs()
                else:
                    raise
            jobs = _normalize_jobs(raw_jobs)
            _write_raw_jobs(provider_id, jobs, output_dir)
            # For backward compatibility, also write to canonical RAW_JOBS_JSON.
            if provider_id == "openai":
                RAW_JOBS_JSON.write_text(json.dumps(jobs, indent=2, ensure_ascii=False), encoding="utf-8")
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

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
