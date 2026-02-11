import json
from pathlib import Path

import pytest

from ji_engine.providers.registry import load_providers_config, resolve_provider_ids


def test_load_providers_config_defaults(tmp_path: Path) -> None:
    config_path = tmp_path / "providers.json"
    config_path.write_text(
        """
[
  {
    "provider_id": "alpha",
    "careers_url": "https://example.com/alpha",
    "extraction_mode": "snapshot_json",
    "snapshot_path": "data/alpha.json"
  }
]
""".strip(),
        encoding="utf-8",
    )
    providers = load_providers_config(config_path)
    assert providers[0]["provider_id"] == "alpha"
    assert providers[0]["mode"] == "snapshot"
    assert providers[0]["enabled"] is True
    assert providers[0]["display_name"] == "alpha"
    assert providers[0]["extraction_mode"] == "snapshot_json"
    assert providers[0]["careers_urls"] == ["https://example.com/alpha"]
    assert providers[0]["allowed_domains"] == ["example.com"]


def test_load_providers_config_is_sorted_and_deterministic(tmp_path: Path) -> None:
    config_path = tmp_path / "providers.json"
    config_path.write_text(
        """
{
  "schema_version": 1,
  "providers": [
    {
      "provider_id": "zeta",
      "careers_urls": ["https://zeta.example/jobs"],
      "extraction_mode": "snapshot_json",
      "snapshot_path": "data/zeta.json"
    },
    {
      "provider_id": "alpha",
      "careers_urls": ["https://alpha.example/jobs"],
      "extraction_mode": "snapshot_json",
      "snapshot_path": "data/alpha.json"
    }
  ]
}
""".strip(),
        encoding="utf-8",
    )
    first = load_providers_config(config_path)
    second = load_providers_config(config_path)
    assert [p["provider_id"] for p in first] == ["alpha", "zeta"]
    assert first == second


def test_load_providers_config_rejects_duplicate_provider_ids(tmp_path: Path) -> None:
    config_path = tmp_path / "providers.json"
    config_path.write_text(
        """
[
  {"provider_id":"dup","careers_url":"https://a.example/jobs","snapshot_path":"data/a.json","extraction_mode":"snapshot_json"},
  {"provider_id":"dup","careers_url":"https://b.example/jobs","snapshot_path":"data/b.json","extraction_mode":"snapshot_json"}
]
""".strip(),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate provider_id"):
        load_providers_config(config_path)


def test_load_providers_config_politeness_defaults_and_overrides(tmp_path: Path) -> None:
    config_path = tmp_path / "providers.json"
    config_path.write_text(
        """
{
  "schema_version": 1,
  "providers": [
    {
      "provider_id": "alpha",
      "careers_urls": ["https://alpha.example/jobs"],
      "extraction_mode": "jsonld",
      "snapshot_path": "data/alpha/index.html",
      "politeness": {
        "defaults": {
          "max_qps": 2.0,
          "max_attempts": 3
        },
        "host_overrides": {
          "alpha.example": {
            "max_qps": 1.0,
            "max_inflight_per_host": 1
          }
        }
      }
    }
  ]
}
""".strip(),
        encoding="utf-8",
    )
    providers = load_providers_config(config_path)
    politeness = providers[0]["politeness"]
    assert politeness["max_qps"] == 2.0
    assert politeness["min_delay_s"] == 0.5
    assert politeness["host_qps_caps"] == {"alpha.example": 1.0}
    assert politeness["host_concurrency_caps"] == {"alpha.example": 1}


def test_adding_provider_entry_changes_registry_predictably(tmp_path: Path) -> None:
    config_path = tmp_path / "providers.json"
    base_payload = {
        "schema_version": 1,
        "providers": [
            {
                "provider_id": "alpha",
                "careers_urls": ["https://alpha.example/jobs"],
                "extraction_mode": "snapshot_json",
                "snapshot_path": "data/alpha.json",
            }
        ],
    }
    config_path.write_text(json.dumps(base_payload), encoding="utf-8")
    before = load_providers_config(config_path)
    assert [entry["provider_id"] for entry in before] == ["alpha"]

    base_payload["providers"].append(
        {
            "provider_id": "beta",
            "careers_urls": ["https://beta.example/jobs"],
            "extraction_mode": "snapshot_json",
            "snapshot_path": "data/beta.json",
        }
    )
    config_path.write_text(json.dumps(base_payload), encoding="utf-8")
    after = load_providers_config(config_path)

    assert [entry["provider_id"] for entry in after] == ["alpha", "beta"]
    assert resolve_provider_ids("all", after) == ["alpha", "beta"]


def test_provider_registry_entry_interface_is_stable() -> None:
    providers = load_providers_config(Path("config/providers.json"))
    openai = next(entry for entry in providers if entry["provider_id"] == "openai")
    assert openai["display_name"] == openai["name"]
    assert openai["careers_url"] == openai["careers_urls"][0]
    assert openai["board_url"] == openai["careers_urls"][0]
    assert openai["type"] == openai["extraction_mode"]


def test_load_providers_config_rejects_unknown_keys(tmp_path: Path) -> None:
    config_path = tmp_path / "providers.json"
    config_path.write_text(
        """
{
  "schema_version": 1,
  "providers": [
    {
      "provider_id": "alpha",
      "careers_urls": ["https://alpha.example/jobs"],
      "extraction_mode": "jsonld",
      "snapshot_path": "data/alpha/index.html",
      "unknown_key": "nope"
    }
  ]
}
""".strip(),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unsupported provider keys"):
        load_providers_config(config_path)


def test_load_providers_config_rejects_missing_extraction_mode(tmp_path: Path) -> None:
    config_path = tmp_path / "providers.json"
    config_path.write_text(
        """
{
  "schema_version": 1,
  "providers": [
    {
      "provider_id": "alpha",
      "careers_urls": ["https://alpha.example/jobs"],
      "snapshot_path": "data/alpha/index.html"
    }
  ]
}
""".strip(),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="missing extraction_mode/type"):
        load_providers_config(config_path)


def test_load_providers_config_rejects_llm_fallback_temp(tmp_path: Path) -> None:
    config_path = tmp_path / "providers.json"
    config_path.write_text(
        """
{
  "schema_version": 1,
  "providers": [
    {
      "provider_id": "alpha",
      "careers_urls": ["https://alpha.example/jobs"],
      "extraction_mode": "jsonld",
      "snapshot_path": "data/alpha/index.html",
      "llm_fallback": {
        "enabled": true,
        "cache_dir": "state/llm_cache",
        "temperature": 0.2
      }
    }
  ]
}
""".strip(),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="llm_fallback.temperature"):
        load_providers_config(config_path)


def test_load_providers_config_supports_new_contract_fields_and_aliases(tmp_path: Path) -> None:
    config_path = tmp_path / "providers.json"
    config_path.write_text(
        """
{
  "schema_version": 1,
  "providers": [
    {
      "provider_id": "beta",
      "display_name": "Beta Corp",
      "enabled": false,
      "careers_urls": ["https://beta.example/jobs"],
      "allowed_domains": ["beta.example"],
      "extraction_mode": "html_rules",
      "update_cadence": "daily",
      "snapshot_path": "data/beta/index.html"
    },
    {
      "provider_id": "alpha",
      "display_name": "Alpha Corp",
      "enabled": true,
      "careers_urls": ["https://alpha.example/jobs"],
      "allowed_domains": ["alpha.example"],
      "extraction_mode": "ashby_api",
      "update_cadence": "hourly",
      "snapshot_path": "data/alpha/index.html"
    }
  ]
}
""".strip(),
        encoding="utf-8",
    )

    providers = load_providers_config(config_path)
    assert [item["provider_id"] for item in providers] == ["alpha", "beta"]
    assert providers[0]["display_name"] == "Alpha Corp"
    assert providers[0]["enabled"] is True
    assert providers[0]["extraction_mode"] == "ashby"
    assert providers[0]["update_cadence"] == "hourly"
    assert providers[1]["enabled"] is False
    assert providers[1]["extraction_mode"] == "html_list"


def test_resolve_provider_ids_all_includes_enabled_only(tmp_path: Path) -> None:
    config_path = tmp_path / "providers.json"
    config_path.write_text(
        """
{
  "schema_version": 1,
  "providers": [
    {
      "provider_id": "alpha",
      "display_name": "Alpha",
      "enabled": true,
      "careers_urls": ["https://alpha.example/jobs"],
      "extraction_mode": "jsonld"
    },
    {
      "provider_id": "beta",
      "display_name": "Beta",
      "enabled": false,
      "careers_urls": ["https://beta.example/jobs"],
      "extraction_mode": "jsonld"
    }
  ]
}
""".strip(),
        encoding="utf-8",
    )
    providers = load_providers_config(config_path)
    assert resolve_provider_ids("all", providers) == ["alpha"]


def test_resolve_provider_ids_rejects_disabled_provider(tmp_path: Path) -> None:
    config_path = tmp_path / "providers.json"
    config_path.write_text(
        """
{
  "schema_version": 1,
  "providers": [
    {
      "provider_id": "alpha",
      "display_name": "Alpha",
      "enabled": false,
      "careers_urls": ["https://alpha.example/jobs"],
      "extraction_mode": "jsonld"
    }
  ]
}
""".strip(),
        encoding="utf-8",
    )
    providers = load_providers_config(config_path)
    with pytest.raises(ValueError, match="disabled in config"):
        resolve_provider_ids("alpha", providers)


def test_load_providers_config_rejects_llm_fallback_mode_without_enabled_fallback(tmp_path: Path) -> None:
    config_path = tmp_path / "providers.json"
    config_path.write_text(
        """
{
  "schema_version": 1,
  "providers": [
    {
      "provider_id": "alpha",
      "display_name": "Alpha",
      "enabled": true,
      "careers_urls": ["https://alpha.example/jobs"],
      "extraction_mode": "llm_fallback"
    }
  ]
}
""".strip(),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="requires llm_fallback.enabled=true"):
        load_providers_config(config_path)


def test_load_providers_config_integration_expected_objects_stable_order(tmp_path: Path) -> None:
    config_path = tmp_path / "providers.json"
    config_path.write_text(
        """
{
  "schema_version": 1,
  "providers": [
    {
      "provider_id": "zeta",
      "display_name": "Zeta",
      "enabled": true,
      "careers_urls": ["https://zeta.example/jobs"],
      "allowed_domains": ["zeta.example"],
      "extraction_mode": "html_rules",
      "update_cadence": "daily"
    },
    {
      "provider_id": "alpha",
      "display_name": "Alpha",
      "enabled": true,
      "careers_urls": ["https://alpha.example/jobs"],
      "allowed_domains": ["alpha.example"],
      "extraction_mode": "ashby_api",
      "update_cadence": "hourly"
    }
  ]
}
""".strip(),
        encoding="utf-8",
    )

    providers = load_providers_config(config_path)
    projection = [
        {
            "provider_id": item["provider_id"],
            "display_name": item["display_name"],
            "enabled": item["enabled"],
            "careers_urls": item["careers_urls"],
            "allowed_domains": item["allowed_domains"],
            "extraction_mode": item["extraction_mode"],
            "update_cadence": item["update_cadence"],
        }
        for item in providers
    ]
    assert projection == [
        {
            "provider_id": "alpha",
            "display_name": "Alpha",
            "enabled": True,
            "careers_urls": ["https://alpha.example/jobs"],
            "allowed_domains": ["alpha.example"],
            "extraction_mode": "ashby",
            "update_cadence": "hourly",
        },
        {
            "provider_id": "zeta",
            "display_name": "Zeta",
            "enabled": True,
            "careers_urls": ["https://zeta.example/jobs"],
            "allowed_domains": ["zeta.example"],
            "extraction_mode": "html_list",
            "update_cadence": "daily",
        },
    ]
