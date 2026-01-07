from __future__ import annotations

import json
from pathlib import Path

from scripts.score_jobs import write_application_kit_md
from ji_engine.ai.provider import StubProvider
from ji_engine.ai.cache import FileSystemAICache
from ji_engine.ai.schema import ensure_ai_payload


def test_application_kit_md_sections(tmp_path: Path) -> None:
    job = {
        "title": "Solutions Architect",
        "apply_url": "http://example.com/job",
        "location": "Remote",
        "team": "Customer Engineering",
        "ai": ensure_ai_payload(
            {
                "match_score": 87,
                "summary_bullets": ["Directly relevant to enterprise deployments", "Proven customer success impact"],
                "skills_required": ["Kubernetes", "Terraform", "Observability"],
            }
        ),
    }
    out_md = tmp_path / "kit.md"
    cache = FileSystemAICache(root=tmp_path / "ai_cache")
    write_application_kit_md([job], out_md, StubProvider(), cache)

    content = out_md.read_text()
    assert "Role snapshot" in content
    assert "Match summary" in content
    assert "Skill gaps (top 3)" in content
    assert "Resume bullets (tailored)" in content
    assert "Interview prep" in content
    assert "2-week plan (daily)" in content

    # Ensure deterministic count expectations
    assert content.count("Day 1:") == 1
    assert content.count("Day 14:") == 1

