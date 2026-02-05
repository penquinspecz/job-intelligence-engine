import importlib
import json

import scripts.run_scrape as run_scrape


def test_run_scrape_defaults_to_ashby_cache(tmp_path, monkeypatch) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    snapshot_path = data_dir / "openai_snapshots" / "index.html"
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot_path.write_text(
        "<html>jobs.ashbyhq.com</html>" + (" " * 2000),
        encoding="utf-8",
    )

    providers_path = tmp_path / "providers.json"
    providers_path.write_text(
        json.dumps(
            [
                {
                    "provider_id": "openai",
                    "type": "ashby",
                    "board_url": "https://jobs.ashbyhq.com/openai",
                    "snapshot_dir": str(snapshot_path.parent),
                    "snapshot_path": str(snapshot_path),
                    "mode": "snapshot",
                }
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("JOBINTEL_DATA_DIR", str(data_dir))
    import ji_engine.config as config

    importlib.reload(config)
    importlib.reload(run_scrape)

    monkeypatch.setattr(run_scrape.AshbyProvider, "_parse_html", lambda *_: [])
    rc = run_scrape.main(
        [
            "--providers",
            "openai",
            "--providers-config",
            str(providers_path),
        ]
    )
    assert rc == 0

    out_path = data_dir / "ashby_cache" / "openai_raw_jobs.json"
    assert out_path.exists()
