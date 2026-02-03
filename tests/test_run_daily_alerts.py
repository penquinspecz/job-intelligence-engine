from pathlib import Path
from types import SimpleNamespace

import scripts.run_daily as run_daily


def test_dispatch_alerts_skips_webhook_when_no_changes(monkeypatch):
    called = []

    def fake_post(webhook: str, message: str) -> bool:
        called.append((webhook, message))
        return True

    monkeypatch.setattr(run_daily, "_post_discord", fake_post)

    args = SimpleNamespace(no_post=False, us_only=False, min_alert_score=80)

    run_daily._dispatch_alerts(
        profile="cs",
        webhook="https://discord.com/api/webhooks/test",
        new_jobs=[],
        changed_jobs=[],
        removed_jobs=[],
        interesting_new=[],
        interesting_changed=[],
        lines=["# placeholder"],
        args=args,
        unavailable_summary="",
    )

    assert not called


def test_maybe_post_run_summary_skips_when_no_diffs(monkeypatch):
    called = []

    def fake_post(*args, **kwargs):
        called.append((args, kwargs))
        return "ok"

    monkeypatch.setattr(run_daily, "_post_run_summary", fake_post)
    status = run_daily._maybe_post_run_summary(
        provider="openai",
        profile="cs",
        ranked_json=Path("dummy.json"),
        diff_counts={"new": 0, "changed": 0, "removed": 0},
        min_score=40,
        notify_mode="diff",
        no_post=False,
    )

    assert status == "skipped"
    assert not called


def test_maybe_post_run_summary_posts_when_diffs_exist(monkeypatch):
    called = []

    def fake_post(*args, **kwargs):
        called.append((args, kwargs))
        return "ok"

    monkeypatch.setattr(run_daily, "_post_run_summary", fake_post)
    status = run_daily._maybe_post_run_summary(
        provider="openai",
        profile="cs",
        ranked_json=Path("dummy.json"),
        diff_counts={"new": 1, "changed": 0, "removed": 0},
        min_score=40,
        notify_mode="diff",
        no_post=False,
    )

    assert status == "ok"
    assert len(called) == 1
