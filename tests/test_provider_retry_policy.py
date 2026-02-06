from __future__ import annotations

import pytest

from ji_engine.providers import retry as provider_retry


class _Resp:
    def __init__(self, status_code: int, text: str) -> None:
        self.status_code = status_code
        self.text = text

    def json(self):
        raise ValueError("no json")


def test_fetch_text_with_retry_retries_on_5xx(monkeypatch) -> None:
    provider_retry.reset_politeness_state()
    monkeypatch.setenv("JOBINTEL_PROVIDER_MIN_DELAY_S", "0")
    monkeypatch.setenv("JOBINTEL_PROVIDER_BACKOFF_JITTER_S", "0")
    calls = {"count": 0}

    def fake_get(url, headers=None, timeout=20):
        calls["count"] += 1
        if calls["count"] == 1:
            return _Resp(500, "error")
        return _Resp(200, "<html>ok</html>")

    monkeypatch.setattr(provider_retry.requests, "get", fake_get)

    text = provider_retry.fetch_text_with_retry(
        "https://example.com",
        max_attempts=2,
        backoff_base_s=0.0,
        backoff_max_s=0.0,
    )
    assert text == "<html>ok</html>"
    assert calls["count"] == 2


def test_fetch_text_with_retry_no_retry_on_404(monkeypatch) -> None:
    provider_retry.reset_politeness_state()
    monkeypatch.setenv("JOBINTEL_PROVIDER_MIN_DELAY_S", "0")
    monkeypatch.setenv("JOBINTEL_PROVIDER_BACKOFF_JITTER_S", "0")
    calls = {"count": 0}

    def fake_get(url, headers=None, timeout=20):
        calls["count"] += 1
        return _Resp(404, "not found")

    monkeypatch.setattr(provider_retry.requests, "get", fake_get)

    with pytest.raises(provider_retry.ProviderFetchError) as exc:
        provider_retry.fetch_text_with_retry(
            "https://example.com",
            max_attempts=3,
            backoff_base_s=0.0,
            backoff_max_s=0.0,
        )

    assert exc.value.reason == "unavailable"
    assert exc.value.attempts == 1
    assert calls["count"] == 1
