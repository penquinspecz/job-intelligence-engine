#!/usr/bin/env python3
"""
Entry point to run the job classification pipeline.

Usage (from repo root, with venv active):
  python scripts/run_classify.py
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import List

from ji_engine.config import LABELED_JOBS_JSON, RAW_JOBS_JSON
from ji_engine.models import JobSource, RawJobPosting
from ji_engine.profile_loader import load_candidate_profile
from ji_engine.pipeline.classifier import label_jobs


def _load_raw_jobs(path: Path) -> List[RawJobPosting]:
    if not path.exists():
        raise FileNotFoundError(f"Jobs file not found: {path}")

    jobs: List[RawJobPosting] = []
    data = json.loads(path.read_text(encoding="utf-8"))

    for d in data:
        # Normalize types for RawJobPosting(**d)
        d["source"] = JobSource(d["source"])
        d["scraped_at"] = datetime.fromisoformat(d["scraped_at"])
        jobs.append(RawJobPosting(**d))

    return jobs


def main() -> int:
    profile = load_candidate_profile()

    try:
        jobs = _load_raw_jobs(RAW_JOBS_JSON)
    except FileNotFoundError as e:
        print(f"Error: {e}")
        return 1

    labeled = label_jobs(jobs, profile)

    counts = {"RELEVANT": 0, "MAYBE": 0, "IRRELEVANT": 0}
    for result in labeled:
        counts[result["relevance"]] += 1

    print("\nClassification Summary:")
    print(f"  RELEVANT:   {counts['RELEVANT']}")
    print(f"  MAYBE:      {counts['MAYBE']}")
    print(f"  IRRELEVANT: {counts['IRRELEVANT']}")
    print(f"  Total:      {len(labeled)}")

    relevant_jobs = [r for r in labeled if r["relevance"] == "RELEVANT"]
    print(f"\nFirst {min(10, len(relevant_jobs))} RELEVANT jobs:")
    for i, job in enumerate(relevant_jobs[:10], 1):
        print(f"\n{i}. {job['title']}")
        print(f"   {job['apply_url']}")

    # Write labeled jobs to JSON file
    output_data = []
    for job, labeled_result in zip(jobs, labeled):
        output_data.append(
            {
                "title": job.title,
                "apply_url": job.apply_url,
                "detail_url": job.detail_url,
                "location": job.location,
                "team": job.team,
                "relevance": labeled_result["relevance"],
            }
        )

    LABELED_JOBS_JSON.parent.mkdir(parents=True, exist_ok=True)
    LABELED_JOBS_JSON.write_text(
        json.dumps(output_data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print(f"\nWrote labeled jobs to {LABELED_JOBS_JSON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())