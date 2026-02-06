from __future__ import annotations

import json
import logging
from pathlib import Path

from jobintel.discord_notify import build_run_summary_message, post_discord


def test_build_run_summary_message(tmp_path: Path) -> None:
    ranked_path = tmp_path / "ranked.json"
    ranked = [
        {"title": "Role A", "score": 95, "apply_url": "https://example.com/a"},
        {"title": "Role B", "score": 72, "apply_url": "https://example.com/b"},
        {"title": "Role C", "score": 65, "apply_url": "https://example.com/c"},
        {"title": "Role D", "score": 40, "apply_url": "https://example.com/d", "enrich_status": "unavailable"},
    ]
    ranked_path.write_text(json.dumps(ranked), encoding="utf-8")

    msg = build_run_summary_message(
        provider="openai",
        profile="cs",
        ranked_json=ranked_path,
        diff_counts={"new": 1, "changed": 2, "removed": 3},
        min_score=70,
        timestamp="2026-01-22T00:00:00+00:00",
        top_n=3,
        extra_lines=["AI briefs: generated for top 3"],
    )

    assert "JobIntel — openai / cs" in msg
    assert "Deltas: new=1 changed=2 removed=3" in msg
    assert "Shortlist (>= 70): 2" in msg
    assert "- **95** Role A — https://example.com/a" in msg
    assert "- **72** Role B — https://example.com/b" in msg
    assert "AI briefs: generated for top 3" in msg


def test_post_discord_webhook_unset(caplog) -> None:
    caplog.set_level(logging.INFO)
    ok = post_discord("", "hello")
    assert ok is False
    assert any("webhook unset" in record.message.lower() for record in caplog.records)


def test_build_run_summary_message_includes_identity_diff_sections(tmp_path: Path) -> None:
    ranked_path = tmp_path / "ranked.json"
    ranked = [
        {"title": "Role A", "score": 95, "apply_url": "https://example.com/a"},
        {"title": "Role B", "score": 72, "apply_url": "https://example.com/b"},
    ]
    ranked_path.write_text(json.dumps(ranked), encoding="utf-8")

    msg = build_run_summary_message(
        provider="openai",
        profile="cs",
        ranked_json=ranked_path,
        diff_counts={"new": 1, "changed": 1, "removed": 0},
        min_score=70,
        timestamp="2026-01-22T00:00:00+00:00",
        diff_top_n=2,
        diff_items={
            "new": [{"title": "New Role", "score": 88, "apply_url": "https://example.com/new"}],
            "changed": [
                {
                    "title": "Changed Role",
                    "score": 83,
                    "apply_url": "https://example.com/changed",
                    "changed_fields": ["title", "score"],
                }
            ],
        },
    )

    assert "Top new (identity diff, max 2):" in msg
    assert "New Role" in msg
    assert "Top changed (identity diff, max 2):" in msg
    assert "Changed Role" in msg
    assert "changed: title, score" in msg
