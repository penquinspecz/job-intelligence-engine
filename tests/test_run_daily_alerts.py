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
