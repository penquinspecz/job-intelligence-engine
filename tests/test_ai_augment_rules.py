from __future__ import annotations

import json
from pathlib import Path

from ji_engine.ai.cache import FileSystemAICache
from ji_engine.ai.provider import StubProvider, AIProvider
from ji_engine.utils.atomic_write import atomic_write_text
from ji_engine.ai.augment import compute_content_hash
from ji_engine.ai.extract_rules import RULES_VERSION


class MinimalProvider(AIProvider):
    """Provider that returns an intentionally minimal payload to trigger rules backfill."""

    def extract(self, job):  # type: ignore[override]
        return {"summary": "minimal", "confidence": 0.1}


def _patch_cache(monkeypatch, tmp_path: Path):
    from ji_engine.ai import cache as cache_mod

    class _TmpCache(cache_mod.FileSystemAICache):
        def __init__(self, root: Path | None = None):
            super().__init__(root=tmp_path / "ai_cache")

    monkeypatch.setattr("ji_engine.ai.cache.FileSystemAICache", _TmpCache)
    monkeypatch.setattr("ji_engine.ai.augment.FileSystemAICache", _TmpCache)


def test_run_ai_augment_backfills_skills_from_rules(monkeypatch, tmp_path: Path) -> None:
    _patch_cache(monkeypatch, tmp_path)

    enriched = [
        {
            "title": "Solutions Architect (Gov)",
            "location": "DC",
            "team": "Customer Engineering",
            "apply_url": "u1",
            "jd_text": "Requirements: Python, Kubernetes, Terraform. Preferred: RAG. Clearance required.",
        }
    ]
    input_path = tmp_path / "openai_enriched_jobs.json"
    output_path = tmp_path / "openai_enriched_jobs_ai.json"
    atomic_write_text(input_path, json.dumps(enriched, ensure_ascii=False, indent=2))

    monkeypatch.setattr("ji_engine.config.ENRICHED_JOBS_JSON", input_path)
    monkeypatch.setattr("scripts.run_ai_augment.ENRICHED_JOBS_JSON", input_path)
    monkeypatch.setattr("scripts.run_ai_augment.OUTPUT_PATH", output_path)

    from scripts.run_ai_augment import main  # noqa: WPS433

    rc = main(argv=[], provider=MinimalProvider())
    assert rc == 0
    out = json.loads(output_path.read_text(encoding="utf-8"))
    ai = out[0]["ai"]
    assert ai["skills_required"]  # non-empty
    assert "Python" in ai["skills_required"]
    assert "Kubernetes" in ai["skills_required"]
    assert "Security clearance required" in ai["red_flags"]


def test_cached_ai_payload_upgraded_to_new_rules(monkeypatch, tmp_path: Path) -> None:
    _patch_cache(monkeypatch, tmp_path)

    job = {
        "title": "Field Engineer",
        "apply_url": "http://example.com/field",
        "location": "Seattle",
        "team": "Robotics",
        "jd_text": """
        Requirements:
        - Robotics and embedded systems experience.
        - Familiarity with automation, troubleshooting, and CAD.
        Preferred:
        - Experience with controls/PLC and Python scripting.
        """,
    }
    chash = compute_content_hash(job)
    job_id = job["apply_url"]
    cache = FileSystemAICache(root=tmp_path / "ai_cache")
    cache.put(
        job_id,
        chash,
        {
            "summary": "old",
            "confidence": 0.0,
            "skills_required": ["Security"],
            "role_family": "Forward Deployed",
            "seniority": "Staff",
            "red_flags": [],
            "rules_version": "old",
        },
    )

    input_path = tmp_path / "openai_enriched_jobs.json"
    output_path = tmp_path / "openai_enriched_jobs_ai.json"
    atomic_write_text(input_path, json.dumps([job], ensure_ascii=False, indent=2))

    monkeypatch.setattr("ji_engine.config.ENRICHED_JOBS_JSON", input_path)
    monkeypatch.setattr("scripts.run_ai_augment.ENRICHED_JOBS_JSON", input_path)
    monkeypatch.setattr("scripts.run_ai_augment.OUTPUT_PATH", output_path)

    from scripts.run_ai_augment import main  # noqa: WPS433

    main(argv=[], provider=StubProvider())

    data = json.loads(output_path.read_text(encoding="utf-8"))
    ai = data[0]["ai"]
    assert ai["role_family"] == "Robotics"
    assert ai["seniority"] == "IC"
    assert "Robotics" in ai["skills_required"]
    assert "CAD" in ai["skills_required"]
    assert "Troubleshooting" in ai["skills_required"]
    assert "Embedded Systems" in ai["skills_required"]
    assert ai["rules_version"] == RULES_VERSION


