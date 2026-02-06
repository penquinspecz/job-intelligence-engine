import importlib
import json
import logging

import ji_engine.config as config
import scripts.run_scrape as run_scrape_module
from ji_engine.providers.retry import ProviderFetchError


def test_run_scrape_marks_provider_unavailable_on_live_failure(tmp_path, monkeypatch, caplog) -> None:
    data_dir = tmp_path / "data"
    monkeypatch.setenv("JOBINTEL_DATA_DIR", str(data_dir))
    importlib.reload(config)
    run_scrape = importlib.reload(run_scrape_module)

    snapshot_dir = data_dir / "openai_snapshots"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    snapshot_html = "<html><body>" + ("x" * 600) + "</body></html>"
    (snapshot_dir / "index.html").write_text(snapshot_html, encoding="utf-8")

    providers_path = data_dir / "providers.json"
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
                    "live_enabled": True,
                }
            ]
        ),
        encoding="utf-8",
    )

    def fake_scrape_live(self):
        raise ProviderFetchError("auth_error", attempts=2, status_code=403)

    monkeypatch.setattr(run_scrape.AshbyProvider, "scrape_live", fake_scrape_live)

    caplog.set_level(logging.INFO)
    rc = run_scrape.main(["--providers", "openai", "--mode", "LIVE", "--providers-config", str(providers_path)])
    assert rc in (0, None)

    meta_path = data_dir / "ashby_cache" / "openai_scrape_meta.json"
    payload = json.loads(meta_path.read_text(encoding="utf-8"))
    assert payload["availability"] == "unavailable"
    assert payload["unavailable_reason"] == "auth_error"
    assert payload["live_result"] == "blocked"
    assert payload["snapshot_used"] is True
    assert any("[run_scrape][provenance]" in record.message for record in caplog.records)
    assert payload["attempts_made"] == 2
