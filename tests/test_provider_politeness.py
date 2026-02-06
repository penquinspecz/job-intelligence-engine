from __future__ import annotations

import pytest

from ji_engine.providers import retry as provider_retry


class _Resp:
    def __init__(self, status_code: int, text: str) -> None:
        self.status_code = status_code
        self.text = text


def test_rate_limit_enforces_min_delay(monkeypatch) -> None:
    provider_retry.reset_politeness_state()
    monkeypatch.setenv("JOBINTEL_PROVIDER_MIN_DELAY_S", "1.0")
    monkeypatch.setenv("JOBINTEL_PROVIDER_RATE_JITTER_S", "0.2")
    monkeypatch.setenv("JOBINTEL_PROVIDER_BACKOFF_JITTER_S", "0")

    calls = {"sleep_s": []}

    def fake_sleep(duration):
        calls["sleep_s"].append(duration)

    times = iter([0.0, 0.5, 0.5, 0.5])

    monkeypatch.setattr(provider_retry.time, "sleep", fake_sleep)
    monkeypatch.setattr(provider_retry.time, "time", lambda: next(times))
    monkeypatch.setattr(provider_retry.requests, "get", lambda *args, **kwargs: _Resp(200, "<html>ok</html>"))

    provider_retry.fetch_text_with_retry(
        "https://example.com",
        max_attempts=1,
        backoff_base_s=0.0,
        backoff_max_s=0.0,
        provider_id="openai",
    )
    provider_retry.fetch_text_with_retry(
        "https://example.com",
        max_attempts=1,
        backoff_base_s=0.0,
        backoff_max_s=0.0,
        provider_id="openai",
    )

    assert calls["sleep_s"] == [1.2]


def test_backoff_logs_deterministic_sleep(monkeypatch) -> None:
    provider_retry.reset_politeness_state()
    monkeypatch.setenv("JOBINTEL_PROVIDER_MIN_DELAY_S", "0")
    monkeypatch.setenv("JOBINTEL_PROVIDER_BACKOFF_JITTER_S", "0.1")

    calls = {"sleep_s": []}

    def fake_sleep(duration):
        calls["sleep_s"].append(duration)

    def fake_get(url, headers=None, timeout=20):
        if not calls["sleep_s"]:
            return _Resp(500, "error")
        return _Resp(200, "<html>ok</html>")

    monkeypatch.setattr(provider_retry.time, "sleep", fake_sleep)
    monkeypatch.setattr(provider_retry.requests, "get", fake_get)

    provider_retry.fetch_text_with_retry(
        "https://example.com",
        max_attempts=2,
        backoff_base_s=1.0,
        backoff_max_s=4.0,
        provider_id="openai",
    )

    assert calls["sleep_s"] == [1.1]


def test_circuit_breaker_trips_after_failures(monkeypatch) -> None:
    provider_retry.reset_politeness_state()
    monkeypatch.setenv("JOBINTEL_PROVIDER_MIN_DELAY_S", "0")
    monkeypatch.setenv("JOBINTEL_PROVIDER_BACKOFF_JITTER_S", "0")
    monkeypatch.setenv("JOBINTEL_PROVIDER_MAX_CONSEC_FAILS", "2")
    monkeypatch.setenv("JOBINTEL_PROVIDER_COOLDOWN_S", "60")

    calls = {"count": 0}

    def fake_get(*args, **kwargs):
        calls["count"] += 1
        return _Resp(500, "error")

    monkeypatch.setattr(provider_retry.requests, "get", fake_get)

    with pytest.raises(provider_retry.ProviderFetchError) as exc1:
        provider_retry.fetch_text_with_retry(
            "https://example.com",
            max_attempts=1,
            backoff_base_s=0.0,
            backoff_max_s=0.0,
            provider_id="openai",
        )
    assert exc1.value.reason == "network_error"

    with pytest.raises(provider_retry.ProviderFetchError) as exc2:
        provider_retry.fetch_text_with_retry(
            "https://example.com",
            max_attempts=1,
            backoff_base_s=0.0,
            backoff_max_s=0.0,
            provider_id="openai",
        )
    assert exc2.value.reason == "network_error"

    with pytest.raises(provider_retry.ProviderFetchError) as exc3:
        provider_retry.fetch_text_with_retry(
            "https://example.com",
            max_attempts=1,
            backoff_base_s=0.0,
            backoff_max_s=0.0,
            provider_id="openai",
        )
    assert exc3.value.reason == "circuit_breaker"
    assert exc3.value.attempts == 0
    assert calls["count"] == 2


def test_block_page_detection(monkeypatch) -> None:
    provider_retry.reset_politeness_state()
    monkeypatch.setenv("JOBINTEL_PROVIDER_MIN_DELAY_S", "0")
    monkeypatch.setenv("JOBINTEL_PROVIDER_BACKOFF_JITTER_S", "0")

    calls = {"count": 0}

    def fake_get(*args, **kwargs):
        calls["count"] += 1
        return _Resp(200, "<html><title>Just a moment...</title></html>")

    monkeypatch.setattr(provider_retry.requests, "get", fake_get)

    with pytest.raises(provider_retry.ProviderFetchError) as exc:
        provider_retry.fetch_text_with_retry(
            "https://example.com",
            max_attempts=3,
            backoff_base_s=0.0,
            backoff_max_s=0.0,
            provider_id="openai",
        )

    assert exc.value.reason == "blocked"
    assert exc.value.attempts == 1
    assert calls["count"] == 1
