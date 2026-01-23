import importlib
import json

import scripts.run_scrape as run_scrape


def test_openai_provider_uses_ashby(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    snapshot_dir = data_dir / "openai_snapshots"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    (snapshot_dir / "index.html").write_text("<html></html>", encoding="utf-8")

    providers_path = tmp_path / "providers.json"
    providers_path.write_text(
        json.dumps(
            [
                {
                    "provider_id": "openai",
                    "type": "ashby",
                    "board_url": "https://jobs.ashbyhq.com/openai",
                    "mode": "snapshot",
                    "snapshot_dir": str(snapshot_dir),
                    "snapshot_path": str(snapshot_dir / "index.html"),
                    "live_enabled": False,
                }
            ]
        ),
        encoding="utf-8",
    )

    called = {"ashby": 0}

    def fake_load(self):
        called["ashby"] += 1
        return []

    monkeypatch.setattr(run_scrape.AshbyProvider, "load_from_snapshot", fake_load)
    monkeypatch.setenv("JOBINTEL_DATA_DIR", str(data_dir))
    importlib.reload(run_scrape)

    rc = run_scrape.main(
        [
            "--providers",
            "openai",
            "--providers-config",
            str(providers_path),
        ]
    )
    assert rc == 0
    assert called["ashby"] == 1
