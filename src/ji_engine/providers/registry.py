from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import urlparse

SUPPORTED_EXTRACTION_MODES = {"ashby", "jsonld", "snapshot_json", "html_list"}
_EXTRACTION_MODE_ALIASES = {
    "ashby_api": "ashby",
    "ashby": "ashby",
    "openai": "ashby",
    "jsonld": "jsonld",
    "llm_fallback": "jsonld",
    "snapshot_json": "snapshot_json",
    "snapshot": "snapshot_json",
    "html_rules": "html_list",
    "html_list": "html_list",
}
SUPPORTED_SCRAPE_MODES = {"snapshot", "live", "auto"}
SUPPORTED_UPDATE_PRIORITIES = {"low", "normal", "high"}
_PROVIDER_ID_RE = re.compile(r"^[a-z0-9_-]+$")
_PROVIDERS_SCHEMA_CACHE: Dict[str, Any] | None = None
_SCHEMA_PATH = Path(__file__).resolve().parents[3] / "schemas" / "providers.schema.v1.json"


def _load_providers_schema() -> Dict[str, Any]:
    global _PROVIDERS_SCHEMA_CACHE
    if _PROVIDERS_SCHEMA_CACHE is None:
        _PROVIDERS_SCHEMA_CACHE = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    return _PROVIDERS_SCHEMA_CACHE


def _schema_provider_keys(schema: Dict[str, Any]) -> set[str]:
    provider = schema.get("$defs", {}).get("provider", {})
    props = provider.get("properties", {})
    return set(props.keys())


def _schema_top_level_keys(schema: Dict[str, Any]) -> set[str]:
    props = schema.get("properties", {})
    return set(props.keys())


def _validate_top_level_schema(data: Dict[str, Any], schema: Dict[str, Any]) -> None:
    allowed = _schema_top_level_keys(schema)
    unknown = sorted(set(data.keys()) - allowed)
    if unknown:
        raise ValueError(f"unsupported providers config keys: {', '.join(unknown)}")
    if "schema_version" not in data:
        raise ValueError("providers config missing schema_version")
    if data.get("schema_version") != 1:
        raise ValueError(f"unsupported providers schema_version '{data.get('schema_version')}'")
    if "providers" not in data:
        raise ValueError("providers config missing providers list")


def _validate_provider_entry_schema(entry: Dict[str, Any], schema: Dict[str, Any]) -> None:
    allowed = _schema_provider_keys(schema)
    unknown = sorted(set(entry.keys()) - allowed)
    if unknown:
        raise ValueError(f"unsupported provider keys: {', '.join(unknown)}")
    if not entry.get("provider_id"):
        raise ValueError("provider entry missing provider_id")
    has_url = any(entry.get(field) for field in ("careers_urls", "careers_url", "board_url"))
    if not has_url:
        raise ValueError("provider entry missing careers_url/careers_urls/board_url")
    if not (entry.get("extraction_mode") or entry.get("type")):
        raise ValueError("provider entry missing extraction_mode/type")
    if "careers_urls" in entry and not isinstance(entry.get("careers_urls"), list):
        raise ValueError("careers_urls must be a list when provided")
    if "careers_url" in entry and not isinstance(entry.get("careers_url"), str):
        raise ValueError("careers_url must be a string when provided")
    if "board_url" in entry and not isinstance(entry.get("board_url"), str):
        raise ValueError("board_url must be a string when provided")
    if "display_name" in entry and not isinstance(entry.get("display_name"), str):
        raise ValueError("display_name must be a string when provided")
    if "allowed_domains" in entry and not isinstance(entry.get("allowed_domains"), list):
        raise ValueError("allowed_domains must be a list when provided")
    if "update_cadence" in entry and not isinstance(entry.get("update_cadence"), (dict, str)):
        raise ValueError("update_cadence must be an object or string when provided")
    if "politeness" in entry and not isinstance(entry.get("politeness"), dict):
        raise ValueError("politeness must be an object when provided")
    if "enabled" in entry and not isinstance(entry.get("enabled"), bool):
        raise ValueError("enabled must be a boolean when provided")
    if "live_enabled" in entry and not isinstance(entry.get("live_enabled"), bool):
        raise ValueError("live_enabled must be a boolean when provided")
    if "snapshot_enabled" in entry and not isinstance(entry.get("snapshot_enabled"), bool):
        raise ValueError("snapshot_enabled must be a boolean when provided")
    if "llm_fallback" in entry and not isinstance(entry.get("llm_fallback"), dict):
        raise ValueError("llm_fallback must be an object when provided")


def _coerce_extraction_mode(raw_mode: Any, raw_type: Any) -> str:
    candidate = str(raw_mode or raw_type or "snapshot_json").strip().lower()
    candidate = _EXTRACTION_MODE_ALIASES.get(candidate, candidate)
    if candidate not in SUPPORTED_EXTRACTION_MODES:
        raise ValueError(f"unsupported extraction_mode '{candidate}'")
    return candidate


def _coerce_mode(value: Any) -> str:
    mode = str(value or "snapshot").strip().lower()
    if mode not in SUPPORTED_SCRAPE_MODES:
        raise ValueError(f"unsupported mode '{mode}'")
    return mode


def _normalized_url_list(entry: Dict[str, Any]) -> List[str]:
    careers_urls = entry.get("careers_urls")
    if isinstance(careers_urls, list):
        raw_urls = [str(v).strip() for v in careers_urls if str(v).strip()]
    else:
        single = entry.get("careers_url") or entry.get("board_url")
        raw_urls = [str(single).strip()] if single else []
    urls: List[str] = []
    seen: set[str] = set()
    for value in raw_urls:
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError(f"invalid careers URL '{value}'")
        canonical = parsed.geturl()
        if canonical not in seen:
            seen.add(canonical)
            urls.append(canonical)
    if not urls:
        raise ValueError("provider entry missing careers_url/careers_urls")
    return urls


def _allowed_domains(urls: List[str], configured: Any) -> List[str]:
    if isinstance(configured, list):
        domains = sorted({str(v).strip().lower() for v in configured if str(v).strip()})
        if domains:
            return domains
    parsed = []
    for url in urls:
        host = urlparse(url).netloc.strip().lower()
        if host:
            parsed.append(host)
    return sorted(set(parsed))


def _normalize_update_cadence(entry: Dict[str, Any]) -> Dict[str, Any] | str:
    raw = entry.get("update_cadence")
    if raw is None:
        return {}
    if isinstance(raw, str):
        value = raw.strip()
        if not value:
            raise ValueError("update_cadence must be non-empty when provided")
        return value
    if not isinstance(raw, dict):
        raise ValueError("update_cadence must be an object or string when provided")
    out: Dict[str, Any] = {}
    if "min_interval_hours" in raw:
        try:
            value = int(raw["min_interval_hours"])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid update_cadence.min_interval_hours: {raw['min_interval_hours']!r}") from exc
        if value < 1:
            raise ValueError("update_cadence.min_interval_hours must be >= 1")
        out["min_interval_hours"] = value
    if "max_staleness_hours" in raw:
        try:
            value = int(raw["max_staleness_hours"])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid update_cadence.max_staleness_hours: {raw['max_staleness_hours']!r}") from exc
        if value < 1:
            raise ValueError("update_cadence.max_staleness_hours must be >= 1")
        out["max_staleness_hours"] = value
    if "priority" in raw:
        priority = str(raw["priority"]).strip().lower()
        if priority not in SUPPORTED_UPDATE_PRIORITIES:
            raise ValueError(f"invalid update_cadence.priority '{priority}'")
        out["priority"] = priority
    if "schedule_hint" in raw:
        hint = str(raw["schedule_hint"]).strip()
        if not hint:
            raise ValueError("update_cadence.schedule_hint must be non-empty when provided")
        out["schedule_hint"] = hint
    unknown = sorted(set(raw.keys()) - {"min_interval_hours", "max_staleness_hours", "priority", "schedule_hint"})
    if unknown:
        raise ValueError(f"unsupported update_cadence keys: {', '.join(unknown)}")
    return out


def _normalize_llm_fallback(entry: Dict[str, Any]) -> Dict[str, Any]:
    raw = entry.get("llm_fallback")
    if raw is None:
        return {"enabled": False}
    if not isinstance(raw, dict):
        raise ValueError("llm_fallback must be an object when provided")
    unknown = sorted(set(raw.keys()) - {"enabled", "cache_dir", "temperature"})
    if unknown:
        raise ValueError(f"unsupported llm_fallback keys: {', '.join(unknown)}")
    enabled = bool(raw.get("enabled", False))
    cache_dir = str(raw.get("cache_dir") or "").strip()
    temperature = raw.get("temperature", 0)
    try:
        temp_value = float(temperature)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"llm_fallback.temperature must be 0 (got {temperature!r})") from exc
    if abs(temp_value) > 1e-9:
        raise ValueError("llm_fallback.temperature must be 0 for deterministic cache usage")
    if enabled and not cache_dir:
        raise ValueError("llm_fallback.cache_dir is required when enabled")
    return {
        "enabled": enabled,
        "cache_dir": cache_dir,
        "temperature": 0.0,
    }


def _cast_float(raw: Any, field: str) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid {field}: {raw!r}") from exc
    return value


def _cast_int(raw: Any, field: str) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid {field}: {raw!r}") from exc
    return value


def _normalize_politeness_defaults(raw: Dict[str, Any], *, field_prefix: str) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    float_fields = {
        "min_delay_s",
        "rate_jitter_s",
        "backoff_base_s",
        "backoff_max_s",
        "backoff_jitter_s",
        "cooldown_s",
        "max_qps",
    }
    int_fields = {
        "max_attempts",
        "max_consecutive_failures",
        "max_inflight_per_host",
    }
    allowed = float_fields | int_fields
    unknown = sorted(set(raw.keys()) - allowed)
    if unknown:
        raise ValueError(f"unsupported {field_prefix} keys: {', '.join(unknown)}")

    for key in sorted(float_fields):
        if key not in raw:
            continue
        value = _cast_float(raw[key], f"{field_prefix}.{key}")
        if value < 0:
            raise ValueError(f"{field_prefix}.{key} must be >= 0")
        out[key] = value
    for key in sorted(int_fields):
        if key not in raw:
            continue
        value = _cast_int(raw[key], f"{field_prefix}.{key}")
        if key in {"max_attempts", "max_inflight_per_host"} and value < 1:
            raise ValueError(f"{field_prefix}.{key} must be >= 1")
        if key == "max_consecutive_failures" and value < 0:
            raise ValueError(f"{field_prefix}.{key} must be >= 0")
        out[key] = value

    max_qps = out.get("max_qps")
    min_delay_s = out.get("min_delay_s")
    if max_qps is not None and max_qps <= 0:
        raise ValueError(f"{field_prefix}.max_qps must be > 0")
    if max_qps is not None and min_delay_s is None:
        out["min_delay_s"] = 1.0 / max_qps
    elif max_qps is None and min_delay_s is not None and min_delay_s > 0:
        out["max_qps"] = 1.0 / min_delay_s
    elif max_qps is not None and min_delay_s is not None:
        derived_qps = 1.0 / min_delay_s if min_delay_s > 0 else 0.0
        if abs(derived_qps - max_qps) > 1e-6:
            raise ValueError(f"{field_prefix}.max_qps does not match min_delay_s")
    return out


def _normalize_host(host: str, *, field: str) -> str:
    candidate = host.strip().lower()
    if not candidate:
        raise ValueError(f"{field} host key must be non-empty")
    parsed = urlparse(candidate if "://" in candidate else f"https://{candidate}")
    netloc = parsed.netloc.strip().lower()
    if not netloc:
        raise ValueError(f"{field} host key '{host}' is invalid")
    return netloc


def _normalize_politeness(entry: Dict[str, Any]) -> Dict[str, Any]:
    raw = entry.get("politeness") or {}
    if not isinstance(raw, dict):
        raise ValueError("politeness must be an object when provided")
    raw_defaults = raw.get("defaults") or {}
    if not isinstance(raw_defaults, dict):
        raise ValueError("politeness.defaults must be an object when provided")

    legacy_defaults: Dict[str, Any] = {}
    for key in (
        "min_delay_s",
        "rate_jitter_s",
        "max_attempts",
        "backoff_base_s",
        "backoff_max_s",
        "backoff_jitter_s",
        "max_consecutive_failures",
        "cooldown_s",
        "max_inflight_per_host",
        "max_qps",
    ):
        if key in raw:
            legacy_defaults[key] = raw[key]
    defaults = _normalize_politeness_defaults({**raw_defaults, **legacy_defaults}, field_prefix="politeness.defaults")

    host_overrides: Dict[str, Dict[str, Any]] = {}
    raw_host_overrides = raw.get("host_overrides") or {}
    if not isinstance(raw_host_overrides, dict):
        raise ValueError("politeness.host_overrides must be an object when provided")
    for raw_host in sorted(raw_host_overrides.keys()):
        host_cfg = raw_host_overrides[raw_host]
        if not isinstance(host_cfg, dict):
            raise ValueError(f"politeness.host_overrides.{raw_host} must be an object")
        host = _normalize_host(raw_host, field="politeness.host_overrides")
        host_overrides[host] = _normalize_politeness_defaults(
            host_cfg,
            field_prefix=f"politeness.host_overrides.{host}",
        )

    raw_qps_caps = raw.get("host_qps_caps") or {}
    if raw_qps_caps and not isinstance(raw_qps_caps, dict):
        raise ValueError("politeness.host_qps_caps must be an object when provided")
    for raw_host in sorted(raw_qps_caps.keys()):
        host = _normalize_host(raw_host, field="politeness.host_qps_caps")
        value = _cast_float(raw_qps_caps[raw_host], f"politeness.host_qps_caps.{host}")
        if value <= 0:
            raise ValueError(f"politeness.host_qps_caps.{host} must be > 0")
        host_overrides.setdefault(host, {})["max_qps"] = value
        host_overrides[host]["min_delay_s"] = 1.0 / value

    raw_concurrency_caps = raw.get("host_concurrency_caps") or {}
    if raw_concurrency_caps and not isinstance(raw_concurrency_caps, dict):
        raise ValueError("politeness.host_concurrency_caps must be an object when provided")
    for raw_host in sorted(raw_concurrency_caps.keys()):
        host = _normalize_host(raw_host, field="politeness.host_concurrency_caps")
        value = _cast_int(raw_concurrency_caps[raw_host], f"politeness.host_concurrency_caps.{host}")
        if value < 1:
            raise ValueError(f"politeness.host_concurrency_caps.{host} must be >= 1")
        host_overrides.setdefault(host, {})["max_inflight_per_host"] = value

    allowed_root_keys = {
        "defaults",
        "host_overrides",
        "host_qps_caps",
        "host_concurrency_caps",
        "min_delay_s",
        "rate_jitter_s",
        "max_attempts",
        "backoff_base_s",
        "backoff_max_s",
        "backoff_jitter_s",
        "max_consecutive_failures",
        "cooldown_s",
        "max_inflight_per_host",
        "max_qps",
    }
    unknown = sorted(set(raw.keys()) - allowed_root_keys)
    if unknown:
        raise ValueError(f"unsupported politeness keys: {', '.join(unknown)}")

    out: Dict[str, Any] = dict(defaults)
    if defaults:
        out["defaults"] = dict(defaults)
    if host_overrides:
        out["host_overrides"] = {host: host_overrides[host] for host in sorted(host_overrides)}
        host_qps_caps: Dict[str, float] = {}
        host_concurrency_caps: Dict[str, int] = {}
        for host, override in out["host_overrides"].items():
            if "max_qps" in override:
                host_qps_caps[host] = float(override["max_qps"])
            if "max_inflight_per_host" in override:
                host_concurrency_caps[host] = int(override["max_inflight_per_host"])
        if host_qps_caps:
            out["host_qps_caps"] = host_qps_caps
        if host_concurrency_caps:
            out["host_concurrency_caps"] = host_concurrency_caps
    return out


def _normalize_provider_entry(entry: Dict[str, Any]) -> Dict[str, Any]:
    provider_id = str(entry.get("provider_id") or "").strip()
    if not provider_id:
        raise ValueError("provider entry missing provider_id")
    if not _PROVIDER_ID_RE.fullmatch(provider_id):
        raise ValueError(f"invalid provider_id '{provider_id}'")
    urls = _normalized_url_list(entry)
    raw_extraction_mode = str(entry.get("extraction_mode") or entry.get("type") or "").strip().lower()
    extraction_mode = _coerce_extraction_mode(entry.get("extraction_mode"), entry.get("type"))
    mode = _coerce_mode(entry.get("mode"))

    snapshot_path_raw = entry.get("snapshot_path")
    snapshot_dir_raw = entry.get("snapshot_dir")
    if snapshot_path_raw:
        snapshot_path = str(snapshot_path_raw)
    elif snapshot_dir_raw:
        snapshot_path = str(Path(str(snapshot_dir_raw)) / "index.html")
    elif extraction_mode in {"ashby", "jsonld", "html_list"}:
        snapshot_path = str(Path("data") / f"{provider_id}_snapshots" / "index.html")
    else:
        snapshot_path = str(Path("data") / f"{provider_id}_snapshots" / "jobs.json")

    update_cadence = _normalize_update_cadence(entry)
    display_name = str(entry.get("display_name") or entry.get("name") or provider_id).strip()
    if not display_name:
        raise ValueError("provider entry display_name/name must be non-empty")
    llm_fallback = _normalize_llm_fallback(entry)
    if raw_extraction_mode == "llm_fallback" and not llm_fallback.get("enabled"):
        raise ValueError("extraction_mode 'llm_fallback' requires llm_fallback.enabled=true")
    normalized: Dict[str, Any] = {
        "provider_id": provider_id,
        "display_name": display_name,
        "name": display_name,  # back-compat for existing callers
        "schema_version": 1,
        "enabled": bool(entry.get("enabled", True)),
        "careers_urls": urls,
        "careers_url": urls[0],
        "board_url": urls[0],  # back-compat for existing callers
        "allowed_domains": _allowed_domains(urls, entry.get("allowed_domains")),
        "extraction_mode": extraction_mode,
        "type": extraction_mode,  # back-compat
        "mode": mode,
        "live_enabled": bool(entry.get("live_enabled", True)),
        "snapshot_enabled": bool(entry.get("snapshot_enabled", True)),
        "snapshot_path": snapshot_path,
        "snapshot_dir": str(Path(snapshot_path).parent),
        "llm_fallback": llm_fallback,
        "update_cadence": update_cadence,
        "politeness": _normalize_politeness(entry),
    }
    return normalized


def load_providers_config(path: Path) -> List[Dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    schema = _load_providers_schema()
    if isinstance(data, list):
        entries = data
    elif isinstance(data, dict):
        _validate_top_level_schema(data, schema)
        entries = data.get("providers")
    else:
        raise ValueError("providers config must be a list or object with providers")

    if not isinstance(entries, list):
        raise ValueError("providers config must include a providers list")

    providers: List[Dict[str, Any]] = []
    seen_ids: set[str] = set()
    for item in entries:
        if not isinstance(item, dict):
            raise ValueError("provider entry must be a dict")
        _validate_provider_entry_schema(item, schema)
        normalized = _normalize_provider_entry(item)
        provider_id = normalized["provider_id"]
        if provider_id in seen_ids:
            raise ValueError(f"duplicate provider_id '{provider_id}'")
        seen_ids.add(provider_id)
        providers.append(normalized)
    providers.sort(key=lambda item: item["provider_id"])
    return providers


def resolve_provider_ids(
    providers_arg: str | None,
    providers_cfg: List[Dict[str, Any]],
    *,
    default_provider: str = "openai",
) -> List[str]:
    enabled_map = {entry["provider_id"]: bool(entry.get("enabled", True)) for entry in providers_cfg}
    requested = (providers_arg or "").strip()
    if requested.lower() == "all":
        providers = [entry["provider_id"] for entry in providers_cfg if enabled_map.get(entry["provider_id"], True)]
    else:
        providers = [p.strip() for p in requested.split(",") if p.strip()]
    if requested.lower() == "all" and not providers:
        raise ValueError("No enabled providers configured")
    if not providers:
        providers = [default_provider]

    seen = set()
    out: List[str] = []
    for provider in providers:
        if provider not in seen:
            seen.add(provider)
            out.append(provider)

    known = {entry["provider_id"] for entry in providers_cfg}
    unknown = [provider for provider in out if provider not in known]
    if unknown:
        unknown_list = ", ".join(unknown)
        raise ValueError(f"Unknown provider_id(s): {unknown_list}")
    disabled = [provider for provider in out if not enabled_map.get(provider, True)]
    if disabled:
        disabled_list = ", ".join(disabled)
        raise ValueError(f"Provider(s) disabled in config: {disabled_list}")
    return out
