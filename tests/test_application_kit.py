from __future__ import annotations

import json
from pathlib import Path
from typing import Any, List

import scripts.score_jobs as score_mod
from ji_engine.ai.provider import AIProvider


class FakeProvider(AIProvider):
    def __init__(self):
        self.calls: List[str] = []

    def extract(self, job: dict) -> dict:
        return {}

    def application_kit(self, job: dict) -> dict:
        self.calls.append(job.get("apply_url", ""))
        return {
            "resume_bullets": ["b1"],
            "cover_letter_points": ["c1"],
            "interview_prompts": ["i1"],
            "gap_plan": ["g1"],
        }


def test_application_kit_uses_cache(tmp_path: Path, monkeypatch) -> None:
    jobs = [
        {
            "title": "Role A",
            "apply_url": "u1",
            "jd_text": "desc A",
            "location": "SF",
            "score": 90,
            "enrich_status": "enriched",
        }
    ]
    out_md = tmp_path / "out.md"
    cache_dir = tmp_path / "cache"

    provider = FakeProvider()
    shortlist = [jobs[0]]
    cache = score_mod.FileSystemAICache(root=cache_dir)
    score_mod.write_application_kit_md(shortlist, out_md, provider, cache)
    assert provider.calls == ["u1"]
    # second run uses cache
    cache2 = score_mod.FileSystemAICache(root=cache_dir)
    score_mod.write_application_kit_md(shortlist, out_md, provider, cache2)
    assert provider.calls == ["u1"]
    content = out_md.read_text(encoding="utf-8")
    assert "Resume bullets" in content

