from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, List


def _raw_job(title: str, url: str) -> Dict[str, Any]:
    return {
        "source": "openai",
        "title": title,
        "location": "Remote",
        "team": "Test",
        "apply_url": url,
        "detail_url": url,
        "raw_text": "Sample job text",
        "scraped_at": "2026-01-01T00:00:00+00:00",
    }


def test_run_daily_multi_provider_outputs(tmp_path: Path, monkeypatch: Any) -> None:
    data_dir = tmp_path / "data"
    state_dir = tmp_path / "state"
    data_dir.mkdir()
    state_dir.mkdir()

    (data_dir / "candidate_profile.json").write_text(
        json.dumps({"skills": [], "roles": []}),
        encoding="utf-8",
    )

    provider_snapshots = tmp_path / "snapshots"
    provider_snapshots.mkdir()
    alpha_snapshot = provider_snapshots / "alpha.json"
    beta_snapshot = provider_snapshots / "beta.json"
    alpha_snapshot.write_text(json.dumps([_raw_job("Alpha Role", "https://alpha.example/job1")]), encoding="utf-8")
    beta_snapshot.write_text(json.dumps([_raw_job("Beta Role", "https://beta.example/job2")]), encoding="utf-8")

    providers_config = tmp_path / "providers.json"
    providers_config.write_text(
        json.dumps(
            [
                {
                    "provider_id": "alpha",
                    "careers_url": "https://alpha.example",
                    "mode": "snapshot",
                    "snapshot_path": str(alpha_snapshot),
                },
                {
                    "provider_id": "beta",
                    "careers_url": "https://beta.example",
                    "mode": "snapshot",
                    "snapshot_path": str(beta_snapshot),
                },
            ],
            indent=2,
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("JOBINTEL_DATA_DIR", str(data_dir))
    monkeypatch.setenv("JOBINTEL_STATE_DIR", str(state_dir))
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "")

    import ji_engine.config as config
    import scripts.run_daily as run_daily

    config = importlib.reload(config)
    run_daily = importlib.reload(run_daily)
    run_daily.USE_SUBPROCESS = False

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
            "--providers",
            "alpha,beta",
            "--providers-config",
            str(providers_config),
        ],
    )

    rc = run_daily.main()
    assert rc == 0

    for provider in ("alpha", "beta"):
        assert (data_dir / f"{provider}_raw_jobs.json").exists()
        assert (data_dir / f"{provider}_labeled_jobs.json").exists()
        assert (data_dir / f"{provider}_ranked_jobs.cs.json").exists()
        assert (data_dir / f"{provider}_ranked_jobs.cs.csv").exists()
        assert (data_dir / f"{provider}_shortlist.cs.md").exists()
