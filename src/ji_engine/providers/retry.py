from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from typing import Optional
from urllib import robotparser
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import requests

logger = logging.getLogger(__name__)

_LAST_REQUEST_TS: dict[str, float] = {}
_INFLIGHT_BY_HOST: dict[str, int] = {}
_FAILURES_BY_PROVIDER: dict[str, int] = {}
_CIRCUIT_OPEN_UNTIL: dict[str, float] = {}
_STATE_LOCK = threading.Lock()

_BLOCK_PATTERNS = (
    "just a moment...",
    "verify you are human",
    "access denied",
    "cf-chl",
    "cdn-cgi/challenge-platform",
    "captcha",
    "cloudflare",
    "attention required",
)


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


def _provider_env_name(base: str, provider_id: Optional[str]) -> str:
    if not provider_id:
        return base
    suffix = "".join(ch if ch.isalnum() else "_" for ch in provider_id.upper())
    return f"{base}_{suffix}"


def _get_float_env_for_provider(base: str, provider_id: Optional[str], default: float) -> float:
    return _get_float_env(_provider_env_name(base, provider_id), _get_float_env(base, default))


def _get_int_env_for_provider(base: str, provider_id: Optional[str], default: int) -> int:
    return _get_int_env(_provider_env_name(base, provider_id), _get_int_env(base, default))


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
    if reason in {
        "auth_error",
        "unavailable",
        "blocked",
        "parse_error",
        "invalid_response",
        "circuit_breaker",
        "allowlist_denied",
        "policy_denied",
        "robots_disallow",
        "robots_fetch_failed",
    }:
        return False
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
    if reason in {"auth_error", "unavailable", "blocked", "circuit_breaker"}:
        return "unavailable"
    if reason.startswith("robots_") or reason.startswith("allowlist_") or reason == "policy_denied":
        return "unavailable"
    if reason in {"parse_error", "invalid_response"}:
        return "invalid_response"
    return "transient_error"


def _sleep_backoff(
    *,
    provider_id: Optional[str],
    attempt: int,
    base_s: float,
    max_s: float,
    reason: str,
    status: Optional[int],
) -> None:
    jitter_s = _get_float_env_for_provider("JOBINTEL_PROVIDER_BACKOFF_JITTER_S", provider_id, 0.0)
    delay = min(max_s, base_s * (2 ** (attempt - 1))) + max(0.0, jitter_s)
    logger.info(
        "[provider_retry][backoff] provider=%s attempt=%s sleep_s=%.3f reason=%s status=%s",
        provider_id,
        attempt,
        delay,
        reason,
        status,
    )
    time.sleep(delay)


def _retry_config(
    max_attempts: Optional[int],
    backoff_base_s: Optional[float],
    backoff_max_s: Optional[float],
    provider_id: Optional[str] = None,
) -> tuple[int, float, float]:
    attempts = max_attempts or _get_int_env_for_provider("JOBINTEL_PROVIDER_MAX_ATTEMPTS", provider_id, 3)
    backoff_base = backoff_base_s or _get_float_env_for_provider(
        "JOBINTEL_PROVIDER_BACKOFF_BASE",
        provider_id,
        0.5,
    )
    backoff_max = backoff_max_s or _get_float_env_for_provider(
        "JOBINTEL_PROVIDER_BACKOFF_MAX",
        provider_id,
        3.0,
    )
    return attempts, backoff_base, backoff_max


def _detect_blocked_content(text: str) -> bool:
    lowered = text.lower()
    return any(pattern in lowered for pattern in _BLOCK_PATTERNS)


def _rate_limit(provider_id: Optional[str], url: str) -> None:
    min_delay_s = _get_float_env_for_provider("JOBINTEL_PROVIDER_MIN_DELAY_S", provider_id, 1.0)
    jitter_s = _get_float_env_for_provider("JOBINTEL_PROVIDER_RATE_JITTER_S", provider_id, 0.0)
    if min_delay_s <= 0:
        return
    now = time.time()
    key = provider_id or "default"
    with _STATE_LOCK:
        last_ts = _LAST_REQUEST_TS.get(key)
        if last_ts is None:
            _LAST_REQUEST_TS[key] = now
            return
        delta = now - last_ts
        sleep_s = min_delay_s - delta
        if sleep_s <= 0:
            _LAST_REQUEST_TS[key] = now
            return
        _LAST_REQUEST_TS[key] = now + sleep_s + jitter_s
    logger.info(
        "[provider_retry][rate_limit] provider=%s url=%s sleep_s=%.3f",
        provider_id,
        url,
        sleep_s + max(0.0, jitter_s),
    )
    time.sleep(sleep_s + max(0.0, jitter_s))


class _InflightGuard:
    def __init__(self, host: str, max_inflight: int) -> None:
        self.host = host
        self.max_inflight = max_inflight

    def __enter__(self) -> None:
        if self.max_inflight <= 0:
            return
        while True:
            with _STATE_LOCK:
                current = _INFLIGHT_BY_HOST.get(self.host, 0)
                if current < self.max_inflight:
                    _INFLIGHT_BY_HOST[self.host] = current + 1
                    return
            time.sleep(0.01)

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.max_inflight <= 0:
            return
        with _STATE_LOCK:
            current = _INFLIGHT_BY_HOST.get(self.host, 1)
            _INFLIGHT_BY_HOST[self.host] = max(0, current - 1)


def _check_circuit(provider_id: Optional[str]) -> None:
    if not provider_id:
        return
    threshold = _get_int_env_for_provider("JOBINTEL_PROVIDER_MAX_CONSEC_FAILS", provider_id, 3)
    if threshold <= 0:
        return
    now = time.time()
    with _STATE_LOCK:
        open_until = _CIRCUIT_OPEN_UNTIL.get(provider_id)
        if open_until and now < open_until:
            raise ProviderFetchError("circuit_breaker", attempts=0)
        if open_until and now >= open_until:
            _CIRCUIT_OPEN_UNTIL.pop(provider_id, None)
            _FAILURES_BY_PROVIDER.pop(provider_id, None)


def _record_failure(provider_id: Optional[str], reason: str) -> None:
    if not provider_id:
        return
    if reason not in {"network_error", "timeout", "rate_limited", "blocked"}:
        return
    threshold = _get_int_env_for_provider("JOBINTEL_PROVIDER_MAX_CONSEC_FAILS", provider_id, 3)
    cooldown_s = _get_float_env_for_provider("JOBINTEL_PROVIDER_COOLDOWN_S", provider_id, 300.0)
    if threshold <= 0:
        return
    with _STATE_LOCK:
        count = _FAILURES_BY_PROVIDER.get(provider_id, 0) + 1
        _FAILURES_BY_PROVIDER[provider_id] = count
        if count >= threshold:
            if cooldown_s > 0:
                _CIRCUIT_OPEN_UNTIL[provider_id] = time.time() + cooldown_s
            logger.warning(
                "[provider_retry][circuit_breaker] provider=%s failures=%s cooldown_s=%.3f",
                provider_id,
                count,
                cooldown_s,
            )


def _record_success(provider_id: Optional[str]) -> None:
    if not provider_id:
        return
    with _STATE_LOCK:
        _FAILURES_BY_PROVIDER.pop(provider_id, None)
        _CIRCUIT_OPEN_UNTIL.pop(provider_id, None)


def _parse_allowlist(value: Optional[str]) -> list[str]:
    if not value:
        return []
    return [item.strip().lower() for item in value.split(",") if item.strip()]


def _allowlist_allows(host: str, entries: list[str]) -> bool:
    if not entries:
        return True
    if "*" in entries:
        return True
    for entry in entries:
        if entry.startswith(".") and host.endswith(entry.lstrip(".")):
            return True
        if host == entry:
            return True
    return False


def record_policy_block(provider_id: Optional[str], reason: str) -> None:
    _record_failure(provider_id, "blocked")
    logger.warning("[provider_retry][policy] provider=%s reason=%s", provider_id, reason)


def evaluate_robots_policy(
    url: str,
    *,
    provider_id: Optional[str] = None,
    user_agent: Optional[str] = None,
    fetcher: Optional[callable] = None,
) -> dict[str, object]:
    parsed = urlparse(url)
    host = parsed.netloc
    scheme = parsed.scheme or "https"
    robots_url = f"{scheme}://{host}/robots.txt"

    allowlist = _parse_allowlist(os.environ.get(_provider_env_name("JOBINTEL_LIVE_ALLOWLIST_DOMAINS", provider_id)))
    if not allowlist:
        allowlist = _parse_allowlist(os.environ.get("JOBINTEL_LIVE_ALLOWLIST_DOMAINS"))
    allowlist_allowed = _allowlist_allows(host, allowlist)

    ua = user_agent or os.environ.get(
        "JOBINTEL_USER_AGENT",
        "jobintel-bot/1.0 (+https://github.com/penquinspecz/job-intelligence-engine)",
    )

    decision: dict[str, object] = {
        "provider": provider_id,
        "host": host,
        "robots_url": robots_url,
        "robots_fetched": False,
        "robots_status": None,
        "robots_allowed": None,
        "allowlist_allowed": allowlist_allowed,
        "final_allowed": False,
        "reason": None,
        "user_agent": ua,
        "allowlist_entries": allowlist,
    }

    if not allowlist_allowed:
        decision["reason"] = "allowlist_denied"
        logger.warning(
            "[provider_retry][robots] provider=%s host=%s allowlist_allowed=%s robots_fetched=%s robots_allowed=%s final_allowed=%s reason=%s url=%s",
            provider_id,
            host,
            allowlist_allowed,
            decision["robots_fetched"],
            decision["robots_allowed"],
            decision["final_allowed"],
            decision["reason"],
            url,
        )
        return decision

    try:
        if fetcher is None:
            resp = requests.get(robots_url, timeout=5)
            status = resp.status_code
            text = resp.text
        else:
            status, text = fetcher(robots_url)
        decision["robots_fetched"] = True
        decision["robots_status"] = status
        if status != 200:
            decision["reason"] = f"robots_status_{status}"
            logger.warning(
                "[provider_retry][robots] provider=%s host=%s allowlist_allowed=%s robots_fetched=%s robots_allowed=%s final_allowed=%s reason=%s url=%s",
                provider_id,
                host,
                allowlist_allowed,
                decision["robots_fetched"],
                decision["robots_allowed"],
                decision["final_allowed"],
                decision["reason"],
                url,
            )
            return decision
        rp = robotparser.RobotFileParser()
        rp.parse(text.splitlines())
        allowed = rp.can_fetch(ua, url)
        decision["robots_allowed"] = allowed
        decision["final_allowed"] = bool(allowed)
        decision["reason"] = "ok" if allowed else "robots_disallow"
    except Exception:
        decision["reason"] = "robots_fetch_failed"

    logger.info(
        "[provider_retry][robots] provider=%s host=%s allowlist_allowed=%s robots_fetched=%s robots_allowed=%s final_allowed=%s reason=%s url=%s",
        provider_id,
        host,
        decision["allowlist_allowed"],
        decision["robots_fetched"],
        decision["robots_allowed"],
        decision["final_allowed"],
        decision["reason"],
        url,
    )
    return decision


def get_politeness_policy(provider_id: Optional[str]) -> dict[str, float | int | None]:
    return {
        "min_delay_s": _get_float_env_for_provider("JOBINTEL_PROVIDER_MIN_DELAY_S", provider_id, 1.0),
        "rate_jitter_s": _get_float_env_for_provider("JOBINTEL_PROVIDER_RATE_JITTER_S", provider_id, 0.0),
        "max_attempts": _get_int_env_for_provider("JOBINTEL_PROVIDER_MAX_ATTEMPTS", provider_id, 3),
        "backoff_base_s": _get_float_env_for_provider("JOBINTEL_PROVIDER_BACKOFF_BASE", provider_id, 0.5),
        "backoff_max_s": _get_float_env_for_provider("JOBINTEL_PROVIDER_BACKOFF_MAX", provider_id, 3.0),
        "backoff_jitter_s": _get_float_env_for_provider("JOBINTEL_PROVIDER_BACKOFF_JITTER_S", provider_id, 0.0),
        "max_consecutive_failures": _get_int_env_for_provider("JOBINTEL_PROVIDER_MAX_CONSEC_FAILS", provider_id, 3),
        "cooldown_s": _get_float_env_for_provider("JOBINTEL_PROVIDER_COOLDOWN_S", provider_id, 300.0),
    }


def reset_politeness_state() -> None:
    with _STATE_LOCK:
        _LAST_REQUEST_TS.clear()
        _INFLIGHT_BY_HOST.clear()
        _FAILURES_BY_PROVIDER.clear()
        _CIRCUIT_OPEN_UNTIL.clear()


def fetch_text_with_retry(
    url: str,
    *,
    headers: Optional[dict[str, str]] = None,
    timeout_s: float = 20,
    max_attempts: Optional[int] = None,
    backoff_base_s: Optional[float] = None,
    backoff_max_s: Optional[float] = None,
    provider_id: Optional[str] = None,
) -> str:
    _check_circuit(provider_id)
    attempts, backoff_base, backoff_max = _retry_config(
        max_attempts,
        backoff_base_s,
        backoff_max_s,
        provider_id,
    )
    last_reason = "network_error"
    last_status: Optional[int] = None
    host = urlparse(url).netloc
    max_inflight = _get_int_env_for_provider("JOBINTEL_PROVIDER_MAX_INFLIGHT_PER_HOST", provider_id, 2)

    for attempt in range(1, attempts + 1):
        try:
            _rate_limit(provider_id, url)
            with _InflightGuard(host, max_inflight):
                resp = requests.get(url, headers=headers or {}, timeout=timeout_s)
            last_status = resp.status_code
            if resp.status_code != 200:
                last_reason = _classify_status(resp.status_code)
                if attempt < attempts and _should_retry(last_reason, resp.status_code):
                    _sleep_backoff(
                        provider_id=provider_id,
                        attempt=attempt,
                        base_s=backoff_base,
                        max_s=backoff_max,
                        reason=last_reason,
                        status=last_status,
                    )
                    continue
                _record_failure(provider_id, last_reason)
                raise ProviderFetchError(last_reason, attempt, resp.status_code)

            text = resp.text
            if text and _detect_blocked_content(text):
                last_reason = "blocked"
                _record_failure(provider_id, last_reason)
                raise ProviderFetchError(last_reason, attempt, resp.status_code)
            if not text or "<html" not in text.lower():
                last_reason = "parse_error"
                _record_failure(provider_id, last_reason)
                raise ProviderFetchError(last_reason, attempt, resp.status_code)
            _record_success(provider_id)
            return text
        except requests.Timeout:
            last_reason = "timeout"
        except requests.RequestException:
            last_reason = "network_error"

        if attempt < attempts and _should_retry(last_reason, last_status):
            _sleep_backoff(
                provider_id=provider_id,
                attempt=attempt,
                base_s=backoff_base,
                max_s=backoff_max,
                reason=last_reason,
                status=last_status,
            )
            continue
        _record_failure(provider_id, last_reason)
        raise ProviderFetchError(last_reason, attempt, last_status)

    _record_failure(provider_id, last_reason)
    raise ProviderFetchError(last_reason, attempts, last_status)


def fetch_urlopen_with_retry(
    url: str,
    *,
    headers: Optional[dict[str, str]] = None,
    timeout_s: float = 20,
    max_attempts: Optional[int] = None,
    backoff_base_s: Optional[float] = None,
    backoff_max_s: Optional[float] = None,
    provider_id: Optional[str] = None,
) -> str:
    _check_circuit(provider_id)
    attempts, backoff_base, backoff_max = _retry_config(
        max_attempts,
        backoff_base_s,
        backoff_max_s,
        provider_id,
    )
    last_reason = "network_error"
    last_status: Optional[int] = None
    req = Request(url, headers=headers or {})
    host = urlparse(url).netloc
    max_inflight = _get_int_env_for_provider("JOBINTEL_PROVIDER_MAX_INFLIGHT_PER_HOST", provider_id, 2)

    for attempt in range(1, attempts + 1):
        try:
            _rate_limit(provider_id, url)
            with _InflightGuard(host, max_inflight), urlopen(req, timeout=timeout_s) as resp:
                status = getattr(resp, "status", 200)
                last_status = status
                if status != 200:
                    last_reason = _classify_status(status)
                    if attempt < attempts and _should_retry(last_reason, status):
                        _sleep_backoff(
                            provider_id=provider_id,
                            attempt=attempt,
                            base_s=backoff_base,
                            max_s=backoff_max,
                            reason=last_reason,
                            status=last_status,
                        )
                        continue
                    _record_failure(provider_id, last_reason)
                    raise ProviderFetchError(last_reason, attempt, status)
                text = resp.read().decode("utf-8")
                if text and _detect_blocked_content(text):
                    last_reason = "blocked"
                    _record_failure(provider_id, last_reason)
                    raise ProviderFetchError(last_reason, attempt, status)
                if not text or "<html" not in text.lower():
                    last_reason = "parse_error"
                    _record_failure(provider_id, last_reason)
                    raise ProviderFetchError(last_reason, attempt, status)
                _record_success(provider_id)
                return text
        except HTTPError as exc:
            last_status = exc.code
            last_reason = _classify_status(exc.code)
        except URLError as exc:
            reason_str = str(getattr(exc, "reason", exc))
            last_reason = "timeout" if "timed out" in reason_str.lower() else "network_error"

        if attempt < attempts and _should_retry(last_reason, last_status):
            _sleep_backoff(
                provider_id=provider_id,
                attempt=attempt,
                base_s=backoff_base,
                max_s=backoff_max,
                reason=last_reason,
                status=last_status,
            )
            continue
        _record_failure(provider_id, last_reason)
        raise ProviderFetchError(last_reason, attempt, last_status)

    _record_failure(provider_id, last_reason)
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
    provider_id: Optional[str] = None,
) -> dict:
    _check_circuit(provider_id)
    attempts, backoff_base, backoff_max = _retry_config(
        max_attempts,
        backoff_base_s,
        backoff_max_s,
        provider_id,
    )
    last_reason = "network_error"
    last_status: Optional[int] = None
    host = urlparse(url).netloc
    max_inflight = _get_int_env_for_provider("JOBINTEL_PROVIDER_MAX_INFLIGHT_PER_HOST", provider_id, 2)

    for attempt in range(1, attempts + 1):
        try:
            _rate_limit(provider_id, url)
            with _InflightGuard(host, max_inflight):
                resp = requests.post(url, headers=headers or {}, json=payload or {}, timeout=timeout_s)
            last_status = resp.status_code
            if resp.status_code != 200:
                last_reason = _classify_status(resp.status_code)
                if attempt < attempts and _should_retry(last_reason, resp.status_code):
                    _sleep_backoff(
                        provider_id=provider_id,
                        attempt=attempt,
                        base_s=backoff_base,
                        max_s=backoff_max,
                        reason=last_reason,
                        status=last_status,
                    )
                    continue
                _record_failure(provider_id, last_reason)
                raise ProviderFetchError(last_reason, attempt, resp.status_code)
            try:
                data = resp.json()
            except ValueError as exc:
                last_reason = "invalid_response"
                _record_failure(provider_id, last_reason)
                raise ProviderFetchError(last_reason, attempt, resp.status_code) from exc
            if not isinstance(data, dict):
                last_reason = "invalid_response"
                _record_failure(provider_id, last_reason)
                raise ProviderFetchError(last_reason, attempt, resp.status_code)
            _record_success(provider_id)
            return data
        except requests.Timeout:
            last_reason = "timeout"
        except requests.RequestException:
            last_reason = "network_error"

        if attempt < attempts and _should_retry(last_reason, last_status):
            _sleep_backoff(
                provider_id=provider_id,
                attempt=attempt,
                base_s=backoff_base,
                max_s=backoff_max,
                reason=last_reason,
                status=last_status,
            )
            continue
        _record_failure(provider_id, last_reason)
        raise ProviderFetchError(last_reason, attempt, last_status)

    _record_failure(provider_id, last_reason)
    raise ProviderFetchError(last_reason, attempts, last_status)


__all__ = [
    "ProviderFetchError",
    "classify_failure_type",
    "evaluate_robots_policy",
    "fetch_json_with_retry",
    "fetch_text_with_retry",
    "fetch_urlopen_with_retry",
    "get_politeness_policy",
    "record_policy_block",
    "reset_politeness_state",
]
