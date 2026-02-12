from __future__ import annotations

import json
from pathlib import Path

from jobintel import ai_insights


def test_ai_insights_stub_when_disabled(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(ai_insights, "RUN_METADATA_DIR", tmp_path / "state" / "runs")
    ranked = tmp_path / "ranked.json"
    ranked.write_text(json.dumps([{"title": "Role A", "score": 80}]), encoding="utf-8")
    prompt = tmp_path / "prompt.md"
    prompt.write_text("prompt", encoding="utf-8")

    md_path, json_path, payload = ai_insights.generate_insights(
        provider="openai",
        profile="cs",
        ranked_path=ranked,
        prev_path=None,
        run_id="2026-01-22T00:00:00Z",
        prompt_path=prompt,
        ai_enabled=False,
        ai_reason="ai_disabled",
        model_name="stub",
    )

    assert json_path.exists()
    assert md_path.exists()
    assert payload["status"] == "disabled"
    assert payload["reason"] == "ai_disabled"


def test_ai_insights_metadata_hashes(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(ai_insights, "RUN_METADATA_DIR", tmp_path / "state" / "runs")
    ranked = tmp_path / "ranked.json"
    ranked.write_text(json.dumps([{"title": "Role A", "score": 80}]), encoding="utf-8")
    prompt = tmp_path / "prompt.md"
    prompt.write_text("prompt", encoding="utf-8")

    _, _, payload = ai_insights.generate_insights(
        provider="openai",
        profile="cs",
        ranked_path=ranked,
        prev_path=None,
        run_id="2026-01-22T00:00:00Z",
        prompt_path=prompt,
        ai_enabled=False,
        ai_reason="ai_disabled",
        model_name="stub",
    )

    meta = payload.get("metadata") or {}
    assert meta.get("prompt_version") == "weekly_insights_v3"
    assert meta.get("prompt_sha256")
    assert meta.get("input_hashes", {}).get("ranked")
    assert meta.get("input_hashes", {}).get("insights_input")
    assert meta.get("structured_input_hash")
    assert meta.get("cache_key")


def test_ai_insights_cache_key_changes_when_structured_input_changes(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(ai_insights, "RUN_METADATA_DIR", tmp_path / "state" / "runs")
    ranked = tmp_path / "ranked.json"
    ranked.write_text(json.dumps([{"job_id": "a", "title": "Role A", "score": 80}]), encoding="utf-8")
    prompt = tmp_path / "prompt.md"
    prompt.write_text("prompt", encoding="utf-8")

    _, _, first = ai_insights.generate_insights(
        provider="openai",
        profile="cs",
        ranked_path=ranked,
        prev_path=None,
        run_id="2026-01-22T00:00:00Z",
        prompt_path=prompt,
        ai_enabled=False,
        ai_reason="ai_disabled",
        model_name="stub",
    )
    first_hash = ((first.get("metadata") or {}).get("input_hashes") or {}).get("insights_input")
    first_cache_key = (first.get("metadata") or {}).get("cache_key")
    ranked.write_text(json.dumps([{"job_id": "a", "title": "Role A", "score": 90}]), encoding="utf-8")
    _, _, second = ai_insights.generate_insights(
        provider="openai",
        profile="cs",
        ranked_path=ranked,
        prev_path=None,
        run_id="2026-01-22T00:00:00Z",
        prompt_path=prompt,
        ai_enabled=False,
        ai_reason="ai_disabled",
        model_name="stub",
    )
    second_hash = ((second.get("metadata") or {}).get("input_hashes") or {}).get("insights_input")
    second_cache_key = (second.get("metadata") or {}).get("cache_key")
    assert first_hash
    assert second_hash
    assert first_hash != second_hash
    assert first_cache_key
    assert second_cache_key
    assert first_cache_key != second_cache_key
