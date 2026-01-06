import json
from pathlib import Path

from ji_engine.ai.augment import compute_content_hash, load_cached_ai, save_cached_ai
from ji_engine.ai.cache import FileSystemAICache
from ji_engine.ai.schema import AI_REQUIRED_KEYS
from ji_engine.utils.atomic_write import atomic_write_text


def test_ai_cache_roundtrip(tmp_path: Path):
    job = {"title": "T", "jd_text": "Desc", "location": "L"}
    chash = compute_content_hash(job)
    job_id = "job-1"
    payload = {"summary": "stub", "confidence": 0.0}

    cache = FileSystemAICache(root=tmp_path)

    assert load_cached_ai(job_id, chash, cache=cache) is None
    save_cached_ai(job_id, chash, payload, cache=cache)
    cached = load_cached_ai(job_id, chash, cache=cache)
    assert cached["summary"] == "stub"
    assert cached["confidence"] == 0.0
    assert cached["match_score"] == 0
    assert isinstance(cached["skills_required"], list)


def test_run_ai_augment_updates_schema(tmp_path: Path, monkeypatch):
    # Prepare enriched input
    enriched = [
        {"title": "A", "jd_text": "desc A", "location": "SF", "apply_url": "u1"},
        {"title": "B", "jd_text": "desc B", "location": "NYC", "apply_url": "u2"},
    ]
    input_path = tmp_path / "openai_enriched_jobs.json"
    atomic_write_text(input_path, json.dumps(enriched, ensure_ascii=False, indent=2))

    # Redirect config path
    monkeypatch.setattr("ji_engine.config.ENRICHED_JOBS_JSON", input_path)
    monkeypatch.setattr("scripts.run_ai_augment.ENRICHED_JOBS_JSON", input_path)
    output_path = tmp_path / "openai_enriched_jobs_ai.json"
    monkeypatch.setattr("scripts.run_ai_augment.OUTPUT_PATH", output_path)

    # Run augment
    from scripts.run_ai_augment import main  # noqa: WPS433

    main()

    data = json.loads(output_path.read_text(encoding="utf-8"))
    assert len(data) == 2
    for item in data:
        assert "ai" in item
        assert "ai_content_hash" in item
        assert item["ai"].get("summary", "").startswith("Stub summary")
        for key, typ in AI_REQUIRED_KEYS.items():
            assert key in item["ai"]
            assert isinstance(item["ai"][key], typ)
        assert 0 <= item["ai"]["match_score"] <= 100

