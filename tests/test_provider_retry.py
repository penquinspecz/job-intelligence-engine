import types

import requests

from ji_engine.providers.retry import ProviderFetchError, fetch_text_with_retry


def test_fetch_text_with_retry_rate_limited(monkeypatch) -> None:
    calls = {"count": 0}

    def fake_get(*args, **kwargs):
        calls["count"] += 1
        return types.SimpleNamespace(status_code=429, text="rate limited")

    monkeypatch.setattr(requests, "get", fake_get)
    monkeypatch.setattr("time.sleep", lambda *_args, **_kwargs: None)

    try:
        fetch_text_with_retry("https://example.com", max_attempts=2, backoff_base_s=0, backoff_max_s=0)
    except ProviderFetchError as exc:
        assert exc.reason == "rate_limited"
        assert exc.attempts == 2
        assert exc.status_code == 429
    else:
        raise AssertionError("Expected ProviderFetchError")


def test_fetch_text_with_retry_timeout(monkeypatch) -> None:
    def fake_get(*args, **kwargs):
        raise requests.Timeout("boom")

    monkeypatch.setattr(requests, "get", fake_get)
    monkeypatch.setattr("time.sleep", lambda *_args, **_kwargs: None)

    try:
        fetch_text_with_retry("https://example.com", max_attempts=1, backoff_base_s=0, backoff_max_s=0)
    except ProviderFetchError as exc:
        assert exc.reason == "timeout"
        assert exc.attempts == 1
    else:
        raise AssertionError("Expected ProviderFetchError")
