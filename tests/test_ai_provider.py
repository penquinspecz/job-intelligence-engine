from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from ji_engine.ai.provider import AIProvider
from ji_engine.utils.atomic_write import atomic_write_text


class FakeProvider(AIProvider):
    def __init__(self, payload: Dict[str, Any]):
        self.payload = payload
        self.calls = 0

    def extract(self, job: Dict[str, Any]) -> Dict[str, Any]:
        self.calls += 1
        return dict(self.payload)


def _patch_cache(monkeypatch, tmp_path: Path):
    from ji_engine.ai import cache as cache_mod

    class _TmpCache(cache_mod.FileSystemAICache):
        def __init__(self, root: Path | None = None):
            super().__init__(root=tmp_path / "ai_cache")

    monkeypatch.setattr("ji_engine.ai.cache.FileSystemAICache", _TmpCache)
    monkeypatch.setattr("ji_engine.ai.augment.FileSystemAICache", _TmpCache)


def test_cache_miss_calls_provider_once(monkeypatch, tmp_path: Path):
    _patch_cache(monkeypatch, tmp_path)
    input_path = tmp_path / "openai_enriched_jobs.json"
    output_path = tmp_path / "openai_enriched_jobs_ai.json"
    atomic_write_text(input_path, json.dumps([{"title": "Job1", "jd_text": "Desc", "location": "SF"}]))

    monkeypatch.setattr("ji_engine.config.ENRICHED_JOBS_JSON", input_path)
    monkeypatch.setattr("scripts.run_ai_augment.ENRICHED_JOBS_JSON", input_path)
    monkeypatch.setattr("scripts.run_ai_augment.OUTPUT_PATH", output_path)

    provider = FakeProvider({"summary": "fake", "confidence": 1.0, "skills_required": ["python"]})

    from scripts.run_ai_augment import main  # noqa: WPS433

    main(argv=[], provider=provider)

    assert provider.calls == 1
    data = json.loads(output_path.read_text())
    assert data[0]["ai"]["summary"] == "fake"
    assert data[0]["ai"]["match_score"] == 0  # no candidate profile loaded


def test_cache_hit_skips_provider(monkeypatch, tmp_path: Path):
    _patch_cache(monkeypatch, tmp_path)
    input_path = tmp_path / "openai_enriched_jobs.json"
    output_path = tmp_path / "openai_enriched_jobs_ai.json"
    atomic_write_text(input_path, json.dumps([{"title": "Job1", "jd_text": "Desc", "location": "SF"}]))

    monkeypatch.setattr("ji_engine.config.ENRICHED_JOBS_JSON", input_path)
    monkeypatch.setattr("scripts.run_ai_augment.ENRICHED_JOBS_JSON", input_path)
    monkeypatch.setattr("scripts.run_ai_augment.OUTPUT_PATH", output_path)

    provider = FakeProvider({"summary": "fake", "confidence": 1.0})

    from scripts.run_ai_augment import main  # noqa: WPS433

    main(argv=[], provider=provider)
    main(argv=[], provider=provider)  # second run should hit cache

    assert provider.calls == 1  # no second call


def test_invalid_provider_output_is_normalized(monkeypatch, tmp_path: Path):
    _patch_cache(monkeypatch, tmp_path)
    input_path = tmp_path / "openai_enriched_jobs.json"
    output_path = tmp_path / "openai_enriched_jobs_ai.json"
    atomic_write_text(input_path, json.dumps([{"title": "Job1", "jd_text": "Desc", "location": "SF"}]))

    monkeypatch.setattr("ji_engine.config.ENRICHED_JOBS_JSON", input_path)
    monkeypatch.setattr("scripts.run_ai_augment.ENRICHED_JOBS_JSON", input_path)
    monkeypatch.setattr("scripts.run_ai_augment.OUTPUT_PATH", output_path)

    provider = FakeProvider({"match_score": "oops", "skills_required": "python"})

    from scripts.run_ai_augment import main  # noqa: WPS433

    main(argv=[], provider=provider)

    data = json.loads(output_path.read_text())
    ai = data[0]["ai"]
    assert isinstance(ai["skills_required"], list)
    assert isinstance(ai["match_score"], int)
    assert 0 <= ai["match_score"] <= 100

