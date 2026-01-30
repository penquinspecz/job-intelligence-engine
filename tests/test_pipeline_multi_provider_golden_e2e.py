from __future__ import annotations

import importlib
import json
import sys
from hashlib import sha256
from pathlib import Path
from typing import Dict


def _sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _write_providers_config(path: Path, openai_snapshot: Path, ashby_snapshot_dir: Path) -> None:
    payload = [
        {
            "provider_id": "openai",
            "type": "ashby",
            "board_url": "https://jobs.ashbyhq.com/openai",
            "mode": "snapshot",
            "snapshot_dir": str(openai_snapshot.parent),
        },
        {
            "provider_id": "anthropic",
            "type": "ashby",
            "board_url": "https://jobs.ashbyhq.com/anthropic",
            "mode": "snapshot",
            "snapshot_dir": str(ashby_snapshot_dir),
            "live_enabled": False,
        },
    ]
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def test_pipeline_multi_provider_golden_e2e(tmp_path: Path, monkeypatch, request) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    data_dir = tmp_path / "data"
    state_dir = tmp_path / "state"
    data_dir.mkdir()
    state_dir.mkdir()

    monkeypatch.setenv("JOBINTEL_DATA_DIR", str(data_dir))
    monkeypatch.setenv("JOBINTEL_STATE_DIR", str(state_dir))
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "")

    openai_snapshot_src = repo_root / "data" / "openai_snapshots" / "index.html"
    anthropic_snapshot_src = repo_root / "data" / "anthropic_snapshots" / "index.html"
    openai_snapshot_dest = data_dir / "openai_snapshots" / "index.html"
    anthropic_snapshot_dest = data_dir / "anthropic_snapshots" / "index.html"
    openai_snapshot_dest.parent.mkdir(parents=True, exist_ok=True)
    anthropic_snapshot_dest.parent.mkdir(parents=True, exist_ok=True)
    openai_snapshot_dest.write_text(openai_snapshot_src.read_text(encoding="utf-8"), encoding="utf-8")
    anthropic_snapshot_dest.write_text(anthropic_snapshot_src.read_text(encoding="utf-8"), encoding="utf-8")

    providers_config = tmp_path / "providers.json"
    _write_providers_config(providers_config, openai_snapshot_dest, anthropic_snapshot_dest.parent)

    import ji_engine.config as config
    import scripts.run_daily as run_daily
    import scripts.run_scrape as run_scrape

    importlib.reload(config)
    run_daily = importlib.reload(run_daily)
    run_scrape = importlib.reload(run_scrape)
    run_daily.USE_SUBPROCESS = False

    def fake_scrape_live(self):
        raise RuntimeError("Live scrape failed with status 403 at https://openai.com/careers/search/")

    monkeypatch.setattr(run_scrape.OpenAICareersProvider, "scrape_live", fake_scrape_live)

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_daily.py",
            "--no_subprocess",
            "--no_post",
            "--no_enrich",
            "--profiles",
            "cs",
            "--min_score",
            "70",
            "--providers",
            "openai,anthropic",
            "--providers-config",
            str(providers_config),
        ],
    )

    rc = run_daily.main()
    assert rc == 0

    metadata_files = sorted(run_daily.RUN_METADATA_DIR.glob("*.json"))
    assert metadata_files
    metadata = json.loads(metadata_files[-1].read_text(encoding="utf-8"))
    scrape_prov = metadata["selection"]["scrape_provenance"]
    assert scrape_prov["openai"]["scrape_mode"] in {"snapshot", "live"}
    assert scrape_prov["openai"]["snapshot_sha256"]
    assert scrape_prov["openai"]["parsed_job_count"] > 0
    assert scrape_prov["anthropic"]["scrape_mode"] == "snapshot"
    assert scrape_prov["anthropic"]["snapshot_sha256"]
    assert scrape_prov["anthropic"]["parsed_job_count"] > 0

    hashes: Dict[str, Dict[str, str]] = {}
    job_ids: Dict[str, set[str]] = {}
    for provider in ("openai", "anthropic"):
        ranked_path = data_dir / f"{provider}_ranked_jobs.cs.json"
        assert ranked_path.exists()
        ranked = json.loads(ranked_path.read_text(encoding="utf-8"))
        assert ranked
        assert all(job.get("job_id") for job in ranked)
        hashes.setdefault(provider, {})["cs"] = _sha256(ranked_path)
        job_ids[provider] = {job["job_id"] for job in ranked}

    assert job_ids["openai"].isdisjoint(job_ids["anthropic"])

    # Golden fixtures depend on the pinned dependency set; update when deps change.
    fixture_path = repo_root / "tests" / "fixtures" / "golden" / "multi_provider_hashes.json"
    update_golden = bool(request.config.getoption("--update-golden"))
    if update_golden:
        fixture_path.parent.mkdir(parents=True, exist_ok=True)
        fixture_path.write_text(json.dumps(hashes, indent=2, sort_keys=True), encoding="utf-8")
    else:
        expected = json.loads(fixture_path.read_text(encoding="utf-8"))
        assert hashes == expected
