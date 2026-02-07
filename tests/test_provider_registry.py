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
    "snapshot_path": "data/alpha.json"
  }
]
""".strip(),
        encoding="utf-8",
    )
    providers = load_providers_config(config_path)
    assert providers[0]["provider_id"] == "alpha"
    assert providers[0]["mode"] == "snapshot"
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
  {"provider_id":"dup","careers_url":"https://a.example/jobs","snapshot_path":"data/a.json"},
  {"provider_id":"dup","careers_url":"https://b.example/jobs","snapshot_path":"data/b.json"}
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
    assert openai["careers_url"] == openai["careers_urls"][0]
    assert openai["board_url"] == openai["careers_urls"][0]
    assert openai["type"] == openai["extraction_mode"]
