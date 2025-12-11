#!/usr/bin/env python

"""
Entry point to run the job classification pipeline.

Usage (from repo root, with venv active):

    python scripts/run_classify.py
"""

import json
import sys
from datetime import datetime
from pathlib import Path

# Add <repo_root>/src to sys.path so `import ji_engine` works
ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from ji_engine.models import RawJobPosting, JobSource  # noqa: E402
from ji_engine.profile_loader import load_candidate_profile  # noqa: E402
from ji_engine.pipeline.classifier import label_jobs  # noqa: E402


def main() -> None:
    """Load jobs, classify them, and print results."""
    # Load candidate profile
    profile = load_candidate_profile()

    # Load jobs from JSON
    jobs_path = ROOT / "data" / "openai_raw_jobs.json"
    if not jobs_path.exists():
        print(f"Error: Jobs file not found: {jobs_path}")
        sys.exit(1)

    with open(jobs_path, "r", encoding="utf-8") as f:
        jobs_data = json.load(f)

    # Convert dicts to RawJobPosting instances
    jobs = []
    for d in jobs_data:
        # Convert types for RawJobPosting(**d)
        d["source"] = JobSource(d["source"])
        d["scraped_at"] = datetime.fromisoformat(d["scraped_at"])
        job = RawJobPosting(**d)
        jobs.append(job)

    # Classify jobs
    labeled = label_jobs(jobs, profile)

    # Count by relevance
    counts = {"RELEVANT": 0, "MAYBE": 0, "IRRELEVANT": 0}
    for result in labeled:
        counts[result["relevance"]] += 1

    # Print summary
    print(f"\nClassification Summary:")
    print(f"  RELEVANT:   {counts['RELEVANT']}")
    print(f"  MAYBE:      {counts['MAYBE']}")
    print(f"  IRRELEVANT: {counts['IRRELEVANT']}")
    print(f"  Total:      {len(labeled)}")

    # Print first 10 RELEVANT jobs
    relevant_jobs = [r for r in labeled if r["relevance"] == "RELEVANT"]
    print(f"\nFirst {min(10, len(relevant_jobs))} RELEVANT jobs:")
    for i, job in enumerate(relevant_jobs[:10], 1):
        print(f"\n{i}. {job['title']}")
        print(f"   {job['apply_url']}")


if __name__ == "__main__":
    main()
