from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import requests


@dataclass
class ProviderFetchError(RuntimeError):
    reason: str
    attempts: int
    status_code: Optional[int] = None

    def __str__(self) -> str:
        parts = [self.reason, f"attempts={self.attempts}"]
        if self.status_code is not None:
            parts.append(f"status={self.status_code}")
        return "ProviderFetchError(" + ", ".join(parts) + ")"


def _get_int_env(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _get_float_env(name: str, default: float) -> float:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _classify_status(status: int) -> str:
    if status in (401, 403):
        return "auth_error"
    if status in (404, 410):
        return "unavailable"
    if status == 429:
        return "rate_limited"
    if status in (408, 504):
        return "timeout"
    if 500 <= status <= 599:
        return "network_error"
    return "network_error"


def _should_retry(reason: str, status: Optional[int]) -> bool:
    if reason in {"network_error", "timeout", "rate_limited"}:
        return True
    if status is not None and 500 <= status <= 599:
        return True
    return False


def classify_failure_type(reason: Optional[str]) -> Optional[str]:
    if not reason:
        return None
    if reason in {"network_error", "timeout", "rate_limited"}:
        return "transient_error"
    if reason in {"auth_error", "unavailable"}:
        return "unavailable"
    if reason in {"parse_error", "invalid_response"}:
        return "invalid_response"
    return "transient_error"


def _sleep_backoff(attempt: int, base_s: float, max_s: float) -> None:
    delay = min(max_s, base_s * (2 ** (attempt - 1)))
    time.sleep(delay)


def _retry_config(
    max_attempts: Optional[int],
    backoff_base_s: Optional[float],
    backoff_max_s: Optional[float],
) -> tuple[int, float, float]:
    attempts = max_attempts or _get_int_env("JOBINTEL_PROVIDER_MAX_ATTEMPTS", 3)
    backoff_base = backoff_base_s or _get_float_env("JOBINTEL_PROVIDER_BACKOFF_BASE", 0.5)
    backoff_max = backoff_max_s or _get_float_env("JOBINTEL_PROVIDER_BACKOFF_MAX", 3.0)
    return attempts, backoff_base, backoff_max


def fetch_text_with_retry(
    url: str,
    *,
    headers: Optional[dict[str, str]] = None,
    timeout_s: float = 20,
    max_attempts: Optional[int] = None,
    backoff_base_s: Optional[float] = None,
    backoff_max_s: Optional[float] = None,
) -> str:
    attempts, backoff_base, backoff_max = _retry_config(max_attempts, backoff_base_s, backoff_max_s)
    last_reason = "network_error"
    last_status: Optional[int] = None

    for attempt in range(1, attempts + 1):
        try:
            resp = requests.get(url, headers=headers or {}, timeout=timeout_s)
            last_status = resp.status_code
            if resp.status_code != 200:
                last_reason = _classify_status(resp.status_code)
                if attempt < attempts and _should_retry(last_reason, resp.status_code):
                    _sleep_backoff(attempt, backoff_base, backoff_max)
                    continue
                raise ProviderFetchError(last_reason, attempt, resp.status_code)

            text = resp.text
            if not text or "<html" not in text.lower():
                last_reason = "parse_error"
                raise ProviderFetchError(last_reason, attempt, resp.status_code)
            return text
        except requests.Timeout:
            last_reason = "timeout"
        except requests.RequestException:
            last_reason = "network_error"

        if attempt < attempts and _should_retry(last_reason, last_status):
            _sleep_backoff(attempt, backoff_base, backoff_max)
            continue
        raise ProviderFetchError(last_reason, attempt, last_status)

    raise ProviderFetchError(last_reason, attempts, last_status)


def fetch_urlopen_with_retry(
    url: str,
    *,
    headers: Optional[dict[str, str]] = None,
    timeout_s: float = 20,
    max_attempts: Optional[int] = None,
    backoff_base_s: Optional[float] = None,
    backoff_max_s: Optional[float] = None,
) -> str:
    attempts, backoff_base, backoff_max = _retry_config(max_attempts, backoff_base_s, backoff_max_s)
    last_reason = "network_error"
    last_status: Optional[int] = None
    req = Request(url, headers=headers or {})

    for attempt in range(1, attempts + 1):
        try:
            with urlopen(req, timeout=timeout_s) as resp:
                status = getattr(resp, "status", 200)
                last_status = status
                if status != 200:
                    last_reason = _classify_status(status)
                    if attempt < attempts and _should_retry(last_reason, status):
                        _sleep_backoff(attempt, backoff_base, backoff_max)
                        continue
                    raise ProviderFetchError(last_reason, attempt, status)
                text = resp.read().decode("utf-8")
                if not text or "<html" not in text.lower():
                    last_reason = "parse_error"
                    raise ProviderFetchError(last_reason, attempt, status)
                return text
        except HTTPError as exc:
            last_status = exc.code
            last_reason = _classify_status(exc.code)
        except URLError as exc:
            reason_str = str(getattr(exc, "reason", exc))
            last_reason = "timeout" if "timed out" in reason_str.lower() else "network_error"

        if attempt < attempts and _should_retry(last_reason, last_status):
            _sleep_backoff(attempt, backoff_base, backoff_max)
            continue
        raise ProviderFetchError(last_reason, attempt, last_status)

    raise ProviderFetchError(last_reason, attempts, last_status)


def fetch_json_with_retry(
    url: str,
    *,
    headers: Optional[dict[str, str]] = None,
    payload: Optional[dict[str, object]] = None,
    timeout_s: float = 30,
    max_attempts: Optional[int] = None,
    backoff_base_s: Optional[float] = None,
    backoff_max_s: Optional[float] = None,
) -> dict:
    attempts, backoff_base, backoff_max = _retry_config(max_attempts, backoff_base_s, backoff_max_s)
    last_reason = "network_error"
    last_status: Optional[int] = None

    for attempt in range(1, attempts + 1):
        try:
            resp = requests.post(url, headers=headers or {}, json=payload or {}, timeout=timeout_s)
            last_status = resp.status_code
            if resp.status_code != 200:
                last_reason = _classify_status(resp.status_code)
                if attempt < attempts and _should_retry(last_reason, resp.status_code):
                    _sleep_backoff(attempt, backoff_base, backoff_max)
                    continue
                raise ProviderFetchError(last_reason, attempt, resp.status_code)
            try:
                data = resp.json()
            except ValueError as exc:
                last_reason = "invalid_response"
                raise ProviderFetchError(last_reason, attempt, resp.status_code) from exc
            if not isinstance(data, dict):
                last_reason = "invalid_response"
                raise ProviderFetchError(last_reason, attempt, resp.status_code)
            return data
        except requests.Timeout:
            last_reason = "timeout"
        except requests.RequestException:
            last_reason = "network_error"

        if attempt < attempts and _should_retry(last_reason, last_status):
            _sleep_backoff(attempt, backoff_base, backoff_max)
            continue
        raise ProviderFetchError(last_reason, attempt, last_status)

    raise ProviderFetchError(last_reason, attempts, last_status)


__all__ = [
    "ProviderFetchError",
    "classify_failure_type",
    "fetch_json_with_retry",
    "fetch_text_with_retry",
    "fetch_urlopen_with_retry",
]
