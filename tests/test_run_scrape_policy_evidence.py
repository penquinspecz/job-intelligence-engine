import importlib
import json
import logging
from pathlib import Path

import ji_engine.config as config
import scripts.run_scrape as run_scrape_module


def _write_provider_config(path: Path, snapshot_dir: Path) -> None:
    path.write_text(
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


def _prepare_snapshot(snapshot_dir: Path) -> None:
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    html = "<html><body>jobs.ashbyhq.com " + ("x" * 700) + "</body></html>"
    (snapshot_dir / "index.html").write_text(html, encoding="utf-8")


def _allowed_robots(_url: str, provider_id=None) -> dict:
    return {
        "provider_id": provider_id,
        "host": "jobs.ashbyhq.com",
        "robots_url": "https://jobs.ashbyhq.com/robots.txt",
        "robots_fetched": True,
        "robots_status": 200,
        "robots_allowed": True,
        "allowlist_allowed": True,
        "final_allowed": True,
        "reason": "ok",
        "user_agent": "jobintel-bot/2.0",
        "allowlist_entries": ["jobs.ashbyhq.com"],
    }


def test_policy_summary_line_is_deterministic(tmp_path: Path, monkeypatch, caplog) -> None:
    data_dir = tmp_path / "data"
    monkeypatch.setenv("JOBINTEL_DATA_DIR", str(data_dir))
    monkeypatch.setenv("JOBINTEL_PROVIDER_MIN_DELAY_S_OPENAI", "2")
    monkeypatch.setenv("JOBINTEL_PROVIDER_RATE_JITTER_S_OPENAI", "0.25")
    monkeypatch.setenv("JOBINTEL_PROVIDER_MAX_ATTEMPTS_OPENAI", "4")
    monkeypatch.setenv("JOBINTEL_PROVIDER_BACKOFF_BASE_OPENAI", "0.5")
    monkeypatch.setenv("JOBINTEL_PROVIDER_BACKOFF_MAX_OPENAI", "3.0")
    monkeypatch.setenv("JOBINTEL_PROVIDER_BACKOFF_JITTER_S_OPENAI", "0.1")
    monkeypatch.setenv("JOBINTEL_PROVIDER_MAX_CONSEC_FAILS_OPENAI", "5")
    monkeypatch.setenv("JOBINTEL_PROVIDER_COOLDOWN_S_OPENAI", "120")
    monkeypatch.setenv("JOBINTEL_PROVIDER_MAX_INFLIGHT_PER_HOST_OPENAI", "3")
    monkeypatch.setenv("JOBINTEL_LIVE_ALLOWLIST_DOMAINS_OPENAI", "jobs.ashbyhq.com")
    monkeypatch.setenv("JOBINTEL_USER_AGENT", "jobintel-bot/2.0")

    importlib.reload(config)
    run_scrape = importlib.reload(run_scrape_module)

    snapshot_dir = data_dir / "openai_snapshots"
    _prepare_snapshot(snapshot_dir)
    providers_path = data_dir / "providers.json"
    _write_provider_config(providers_path, snapshot_dir)

    monkeypatch.setattr(run_scrape, "evaluate_robots_policy", _allowed_robots)
    monkeypatch.setattr(
        run_scrape.AshbyProvider,
        "scrape_live",
        lambda self: [{"title": "Example", "apply_url": "https://example.com/job"}],
    )

    caplog.set_level(logging.INFO)
    rc = run_scrape.main(["--providers", "openai", "--mode", "LIVE", "--providers-config", str(providers_path)])
    assert rc in (0, None)

    summary_records = [r.message for r in caplog.records if "[run_scrape][POLICY_SUMMARY]" in r.message]
    assert len(summary_records) == 1
    payload = json.loads(summary_records[0].split("] ", 1)[1])["openai"]
    assert payload == {
        "backoff_config": {
            "base_s": 0.5,
            "jitter_range_s": [0.0, 0.1],
            "max_retries": 3,
            "max_sleep_s": 3.0,
        },
        "chaos_mode_enabled": False,
        "circuit_breaker_config": {"cooldown_s": 120.0, "threshold": 5},
        "rate_limit_config": {
            "jitter_range_s": [0.0, 0.25],
            "min_delay_s": 2.0,
            "per_host_concurrency": 3,
            "qps": 0.5,
        },
        "robots_policy_config": {
            "allowlist_entries": ["jobs.ashbyhq.com"],
            "default_action": "deny",
        },
        "user_agent": "jobintel-bot/2.0",
    }

    meta_path = data_dir / "ashby_cache" / "openai_scrape_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["policy_snapshot"] == payload


def test_chaos_mode_sets_deterministic_provenance_fields(tmp_path: Path, monkeypatch, caplog) -> None:
    data_dir = tmp_path / "data"
    monkeypatch.setenv("JOBINTEL_DATA_DIR", str(data_dir))
    monkeypatch.setenv("JOBINTEL_CHAOS_MODE", "1")
    monkeypatch.setenv("JOBINTEL_CHAOS_PROVIDER", "openai")
    monkeypatch.setenv("JOBINTEL_PROVIDER_MIN_DELAY_S_OPENAI", "0")

    importlib.reload(config)
    run_scrape = importlib.reload(run_scrape_module)

    snapshot_dir = data_dir / "openai_snapshots"
    _prepare_snapshot(snapshot_dir)
    providers_path = data_dir / "providers.json"
    _write_provider_config(providers_path, snapshot_dir)

    monkeypatch.setattr(run_scrape, "evaluate_robots_policy", _allowed_robots)

    def _should_not_be_called(_self):
        raise AssertionError("scrape_live should not run when chaos mode is forcing failure")

    monkeypatch.setattr(run_scrape.AshbyProvider, "scrape_live", _should_not_be_called)

    caplog.set_level(logging.INFO)
    rc = run_scrape.main(["--providers", "openai", "--mode", "LIVE", "--providers-config", str(providers_path)])
    assert rc in (0, None)
    assert any("[run_scrape][chaos]" in record.message for record in caplog.records)

    meta_path = data_dir / "ashby_cache" / "openai_scrape_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["chaos_mode_enabled"] is True
    assert meta["chaos_triggered"] is True
    assert meta["live_result"] == "failed"
    assert meta["live_error_reason"] == "chaos_forced_error"
    assert meta["live_error_type"] == "transient_error"
    assert meta["snapshot_used"] is True
