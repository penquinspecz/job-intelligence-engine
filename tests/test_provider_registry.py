from pathlib import Path

from ji_engine.providers.registry import load_providers_config


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
