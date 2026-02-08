from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

import scripts.run_daily as run_daily


def test_resolve_providers_all_uses_registry(tmp_path: Path) -> None:
    providers_path = tmp_path / "providers.json"
    providers_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "providers": [
                    {
                        "provider_id": "beta",
                        "careers_urls": ["https://beta.example/jobs"],
                        "extraction_mode": "snapshot_json",
                        "snapshot_path": "data/beta.json",
                    },
                    {
                        "provider_id": "alpha",
                        "careers_urls": ["https://alpha.example/jobs"],
                        "extraction_mode": "snapshot_json",
                        "snapshot_path": "data/alpha.json",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    args = argparse.Namespace(providers="all", providers_config=str(providers_path))
    assert run_daily._resolve_providers(args) == ["alpha", "beta"]


def test_resolve_providers_explicit_order_and_dedupe(tmp_path: Path) -> None:
    providers_path = tmp_path / "providers.json"
    providers_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "providers": [
                    {
                        "provider_id": "alpha",
                        "careers_urls": ["https://alpha.example/jobs"],
                        "extraction_mode": "snapshot_json",
                        "snapshot_path": "data/alpha.json",
                    },
                    {
                        "provider_id": "beta",
                        "careers_urls": ["https://beta.example/jobs"],
                        "extraction_mode": "snapshot_json",
                        "snapshot_path": "data/beta.json",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    args = argparse.Namespace(providers="beta,alpha,beta", providers_config=str(providers_path))
    assert run_daily._resolve_providers(args) == ["beta", "alpha"]


def test_resolve_providers_unknown_fails_closed_with_exit_2(tmp_path: Path) -> None:
    providers_path = tmp_path / "providers.json"
    providers_path.write_text(
        json.dumps(
            {
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
        ),
        encoding="utf-8",
    )
    args = argparse.Namespace(providers="alpha,missing", providers_config=str(providers_path))
    with pytest.raises(SystemExit) as exc:
        run_daily._resolve_providers(args)
    assert exc.value.code == 2
