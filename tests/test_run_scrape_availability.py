import importlib
import json

import ji_engine.config as config
import scripts.run_scrape as run_scrape_module
from ji_engine.providers import openai_provider
from ji_engine.providers.retry import ProviderFetchError


def test_run_scrape_marks_provider_unavailable_on_live_failure(tmp_path, monkeypatch) -> None:
    data_dir = tmp_path / "data"
    monkeypatch.setenv("JOBINTEL_DATA_DIR", str(data_dir))
    importlib.reload(config)
    run_scrape = importlib.reload(run_scrape_module)
    monkeypatch.setattr(openai_provider, "SNAPSHOT_DIR", data_dir / "openai_snapshots")

    def fake_scrape_live(self):
        raise ProviderFetchError("rate_limited", attempts=2, status_code=429)

    monkeypatch.setattr(run_scrape.OpenAICareersProvider, "scrape_live", fake_scrape_live)

    rc = run_scrape.main(["--providers", "openai", "--mode", "LIVE"])
    assert rc in (0, None)

    meta_path = data_dir / "openai_scrape_meta.json"
    payload = json.loads(meta_path.read_text(encoding="utf-8"))
    assert payload["availability"] == "unavailable"
    assert payload["unavailable_reason"] == "rate_limited"
    assert payload["attempts_made"] == 2
