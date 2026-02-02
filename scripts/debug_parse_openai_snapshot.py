#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

from ji_engine.utils.verification import compute_sha256_bytes

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from ji_engine.providers.ashby_provider import (  # noqa: E402
    parse_ashby_snapshot_html_with_source,
)


def _job_id_set_hash(job_ids: list[str]) -> str:
    payload = "\n".join(job_ids).encode("utf-8")
    return compute_sha256_bytes(payload)


def main() -> int:
    snapshot_path = Path("data/openai_snapshots/index.html")
    html = snapshot_path.read_text(encoding="utf-8")
    jobs, payload_source = parse_ashby_snapshot_html_with_source(html, strict=True)
    job_ids = sorted([str(job.get("job_id") or "").strip() for job in jobs if job.get("job_id")])

    print(f"json_payload_source: {payload_source or 'none'}")
    print(f"parsed_count: {len(jobs)}")
    print(f"job_id_set_sha256: {_job_id_set_hash(job_ids)}")
    print(f"first_10_job_ids: {job_ids[:10]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
