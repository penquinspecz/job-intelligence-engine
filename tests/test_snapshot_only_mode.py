from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import run_scrape


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_snapshot_only_allows_snapshot_provider(tmp_path: Path, monkeypatch) -> None:
    data_dir = tmp_path / "data"
    providers_cfg = tmp_path / "providers.json"
    snapshot = data_dir / "snapshot.json"
    _write_json(snapshot, [{"id": 1}])
    _write_json(
        providers_cfg,
        [
            {
                "provider_id": "demo",
                "type": "snapshot",
                "careers_url": "https://example.test/demo",
                "snapshot_path": str(snapshot),
                "mode": "snapshot",
                "live_enabled": False,
            }
        ],
    )
    monkeypatch.setenv("JOBINTEL_DATA_DIR", str(data_dir))
    exit_code = run_scrape.main(["--providers", "demo", "--providers-config", str(providers_cfg), "--snapshot-only"])
    assert exit_code == 0


def test_snapshot_only_blocks_live_provider(tmp_path: Path, monkeypatch, caplog) -> None:
    data_dir = tmp_path / "data"
    providers_cfg = tmp_path / "providers.json"
    snapshot = data_dir / "snapshot.json"
    _write_json(snapshot, [{"id": 1}])
    _write_json(
        providers_cfg,
        [
            {
                "provider_id": "demo",
                "type": "snapshot",
                "careers_url": "https://example.test/demo",
                "snapshot_path": str(snapshot),
                "mode": "live",
                "live_enabled": True,
            }
        ],
    )
    monkeypatch.setenv("JOBINTEL_DATA_DIR", str(data_dir))
    with pytest.raises(SystemExit) as excinfo:
        run_scrape.main(["--providers", "demo", "--providers-config", str(providers_cfg), "--snapshot-only"])
    assert excinfo.value.code == 2
    messages = [record.message for record in caplog.records]
    assert any("demo" in message for message in messages)
    assert any("snapshot-only" in message for message in messages)
