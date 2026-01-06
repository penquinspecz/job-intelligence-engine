from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional

from ji_engine.config import RAW_JOBS_JSON
from ji_engine.models import RawJobPosting
from ji_engine.providers.openai_provider import OpenAICareersProvider


class ScraperManager:
    """
    Coordinates scraping from one or more providers.
    For Sprint 1, we only wire up OpenAI.
    """

    def __init__(self, output_dir: str = "data"):
        self.output_path = Path(output_dir)
        self.output_path.mkdir(parents=True, exist_ok=True)

    def scrape_openai(self, mode: str = "SNAPSHOT") -> List[RawJobPosting]:
        # IMPORTANT: do not hardcode "data" here — inherit the manager's output dir
        provider = OpenAICareersProvider(mode=mode, data_dir=str(self.output_path))
        return provider.fetch_jobs()

    def run_all(self, mode: str = "SNAPSHOT", output_file: Optional[Path] = None) -> None:
        all_jobs: List[RawJobPosting] = []

        openai_jobs = self.scrape_openai(mode=mode)
        all_jobs.extend(openai_jobs)

        # Default to canonical artifact path, but allow override
        out_path = output_file or RAW_JOBS_JSON

        payload = [job.to_dict() for job in all_jobs]
        out_path.parent.mkdir(parents=True, exist_ok=True)

        with out_path.open("w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)

        print(f"Scraped {len(all_jobs)} jobs.")
        print(f"Wrote JSON to {out_path.resolve()}")