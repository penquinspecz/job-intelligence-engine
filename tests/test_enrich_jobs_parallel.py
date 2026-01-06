from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any, Dict

import pytest


def test_enrich_jobs_preserves_order_with_threads(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    jobs = [
        {"title": "First", "apply_url": "https://jobs.ashbyhq.com/openai/11111111-1111-1111-1111-111111111111/application", "relevance": "RELEVANT"},
        {"title": "Second", "apply_url": "https://jobs.ashbyhq.com/openai/22222222-2222-2222-2222-222222222222/application", "relevance": "RELEVANT"},
        {"title": "Third", "apply_url": "https://jobs.ashbyhq.com/openai/33333333-3333-3333-3333-333333333333/application", "relevance": "RELEVANT"},
    ]

    labeled_path = tmp_path / "labeled.json"
    enriched_path = tmp_path / "enriched.json"
    labeled_path.write_text(json.dumps(jobs), encoding="utf-8")

    monkeypatch.setattr("ji_engine.config.LABELED_JOBS_JSON", labeled_path)
    monkeypatch.setattr("ji_engine.config.ENRICHED_JOBS_JSON", enriched_path)
    monkeypatch.setattr("scripts.enrich_jobs.LABELED_JOBS_JSON", labeled_path)
    monkeypatch.setattr("scripts.enrich_jobs.ENRICHED_JOBS_JSON", enriched_path)

    # stub fetch_job_posting to ensure deterministic ordering and no network
    def _fake_fetch(org: str, job_id: str, cache_dir: Path) -> Dict[str, Any]:
        time.sleep(0.01)  # introduce slight delay to exercise threading
        return {
            "data": {
                "jobPosting": {
                    "title": f"title-{job_id[-1]}",
                    "locationName": "SF",
                    "teamNames": ["AI"],
                    "descriptionHtml": "<div>desc</div>",
                }
            }
        }

    monkeypatch.setattr("scripts.enrich_jobs.fetch_job_posting", _fake_fetch)

    import scripts.enrich_jobs as mod

    monkeypatch.setattr(sys, "argv", ["enrich_jobs.py", "--max_workers", "2"])
    mod.main()

    data = json.loads(enriched_path.read_text(encoding="utf-8"))
    titles = [item["title"] for item in data]

    assert titles == ["title-1", "title-2", "title-3"]

