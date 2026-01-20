import importlib
from pathlib import Path

import pytest

import scripts.run_scrape as run_scrape


def test_run_scrape_missing_snapshot_exits_2(tmp_path, monkeypatch, caplog) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    providers_path = tmp_path / "providers.json"
    providers_path.write_text(
        (
            '[{"provider_id": "anthropic", "careers_url": "https://example.com", '
            '"mode": "snapshot", "snapshot_path": "data/anthropic_snapshots/index.html"}]'
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("JOBINTEL_DATA_DIR", str(data_dir))
    import ji_engine.config as config

    importlib.reload(config)
    importlib.reload(run_scrape)

    caplog.set_level("ERROR")
    with pytest.raises(SystemExit) as exc:
        run_scrape.main(["--providers", "anthropic", "--providers-config", str(providers_path)])

    assert exc.value.code == 2
    assert "Snapshot not found" in caplog.text
