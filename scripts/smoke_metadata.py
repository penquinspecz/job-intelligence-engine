#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any, Dict, List

from ji_engine.utils.time import utc_now_z

RUN_REPORT_SCHEMA_VERSION = 1


def _utcnow_iso() -> str:
    return utc_now_z(seconds_precision=True)


def _git_sha() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            text=True,
            capture_output=True,
            check=False,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    sha = (result.stdout or "").strip()
    return sha or None


def build_metadata(providers: List[str], profiles: List[str]) -> Dict[str, Any]:
    try:
        import smoke_contract_check as _smoke_contract_check
    except ImportError:  # pragma: no cover - fallback for module execution
        from scripts import smoke_contract_check as _smoke_contract_check

    return {
        "git_sha": _git_sha(),
        "providers": providers,
        "profiles": profiles,
        "timestamp": _utcnow_iso(),
        # Keep smoke metadata dependency-light; CI smoke host intentionally avoids full app deps.
        "run_report_schema_version": RUN_REPORT_SCHEMA_VERSION,
        "smoke_contract_version": _smoke_contract_check.SMOKE_CONTRACT_VERSION,
    }


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Write smoke metadata to JSON.")
    ap.add_argument("--out", required=True, help="Output path for metadata JSON.")
    ap.add_argument("--providers", default="openai", help="Comma-separated providers.")
    ap.add_argument("--profiles", default="cs", help="Comma-separated profiles.")
    args = ap.parse_args(argv)

    providers = [p.strip() for p in args.providers.split(",") if p.strip()]
    profiles = [p.strip() for p in args.profiles.split(",") if p.strip()]
    payload = build_metadata(providers, profiles)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
