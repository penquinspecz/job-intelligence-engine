import argparse

import pytest

import scripts.run_daily as run_daily


def test_validate_config_requires_webhook_for_test_post():
    args = argparse.Namespace(
        profile="cs",
        profiles="",
        us_only=False,
        min_alert_score=85,
        no_post=False,
        test_post=True,
        no_enrich=False,
        ai=False,
        ai_only=False,
        no_subprocess=False,
        log_json=False,
    )
    with pytest.raises(SystemExit) as exc:
        run_daily.validate_config(args, "")
    assert exc.value.code == 2


def test_validate_config_requires_ai_for_ai_only():
    args = argparse.Namespace(
        profile="cs",
        profiles="",
        us_only=False,
        min_alert_score=85,
        no_post=False,
        test_post=False,
        no_enrich=False,
        ai=False,
        ai_only=True,
        no_subprocess=False,
        log_json=False,
    )
    with pytest.raises(SystemExit) as exc:
        run_daily.validate_config(args, "https://discord.com/api/webhooks/x/y")
    assert exc.value.code == 2
