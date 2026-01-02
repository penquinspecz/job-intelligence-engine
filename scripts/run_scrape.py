#!/usr/bin/env python3
import argparse
import os
from ji_engine.scraper import ScraperManager

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["SNAPSHOT", "LIVE", "AUTO"], default=os.getenv("CAREERS_MODE", "AUTO"))
    args = ap.parse_args()

    manager = ScraperManager(output_dir="data")

    if args.mode == "SNAPSHOT":
        manager.run_all(mode="SNAPSHOT")
        return

    if args.mode == "LIVE":
        manager.run_all(mode="LIVE")
        return

    # AUTO: try LIVE, fall back to SNAPSHOT
    try:
        manager.run_all(mode="LIVE")
    except Exception as e:
        print(f"[run_scrape] LIVE failed ({e!r}) → falling back to SNAPSHOT")
        manager.run_all(mode="SNAPSHOT")

if __name__ == "__main__":
    main()
