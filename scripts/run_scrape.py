#!/usr/bin/env python3
from __future__ import annotations

import argparse
import logging
import os

from ji_engine.config import DATA_DIR
from ji_engine.scraper import ScraperManager

logger = logging.getLogger(__name__)


def main() -> int:
    if not logging.getLogger().hasHandlers():
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--mode",
        choices=["SNAPSHOT", "LIVE", "AUTO"],
        default=os.getenv("CAREERS_MODE", "AUTO"),
        help="Scrape mode. Default from CAREERS_MODE env var.",
    )
    args = ap.parse_args()

    # Centralized path (no stringly-typed "data")
    manager = ScraperManager(output_dir=str(DATA_DIR))

    if args.mode == "SNAPSHOT":
        logger.info("manager.run_all(mode=SNAPSHOT)")
        manager.run_all(mode="SNAPSHOT")
        return 0

    if args.mode == "LIVE":
        logger.info("manager.run_all(mode=LIVE)")
        manager.run_all(mode="LIVE")
        return 0

    # AUTO: try LIVE, fall back to SNAPSHOT
    try:
        logger.info("manager.run_all(mode=LIVE)")
        manager.run_all(mode="LIVE")
    except Exception as e:
        logger.warning(f"[run_scrape] LIVE failed ({e!r}) → falling back to SNAPSHOT")
        logger.info("manager.run_all(mode=SNAPSHOT)")
        manager.run_all(mode="SNAPSHOT")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())