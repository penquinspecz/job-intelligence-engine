#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ji_engine.config import DATA_DIR


def _snapshot_dir(provider_id: str, data_dir: Path) -> Path:
    return data_dir / f"{provider_id}_snapshots"


def _metadata_path(snapshot_dir: Path) -> Path:
    return snapshot_dir / "metadata.json"


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Add a provider HTML snapshot from a local file.")
    ap.add_argument("--provider", required=True, help="Provider id (e.g., openai).")
    ap.add_argument("--from-file", required=True, help="Path to local HTML file.")
    ap.add_argument("--write-metadata", action="store_true", help="Write metadata.json alongside snapshot.")
    args = ap.parse_args(argv)

    provider_id = args.provider.strip()
    src = Path(args.from_file).expanduser()
    if not src.exists():
        raise SystemExit(f"Input file not found: {src}")

    data_dir = Path(DATA_DIR)
    snapshot_dir = _snapshot_dir(provider_id, data_dir)
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    dest = snapshot_dir / "index.html"
    shutil.copyfile(src, dest)

    if args.write_metadata:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source_file": str(src),
        }
        _metadata_path(snapshot_dir).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    print(f"Wrote snapshot: {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
