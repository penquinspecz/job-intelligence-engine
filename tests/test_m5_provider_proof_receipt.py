from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from typing import Any, Dict

from ji_engine.providers.registry import load_providers_config, resolve_provider_ids


def _raw_job(title: str, url: str) -> Dict[str, Any]:
    return {
        "source": "fixture",
        "title": title,
        "location": "Remote",
        "team": "Test",
        "apply_url": url,
        "detail_url": url,
        "raw_text": "Deterministic fixture",
        "scraped_at": "2026-02-11T00:00:00+00:00",
    }


def test_registry_resolves_enabled_providers_deterministically(tmp_path: Path) -> None:
    providers_config = tmp_path / "providers.json"
    providers_config.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "providers": [
                    {
                        "provider_id": "zeta",
                        "careers_urls": ["https://zeta.example/jobs"],
                        "extraction_mode": "snapshot_json",
                        "snapshot_path": "data/zeta.json",
                        "enabled": True,
                    },
                    {
                        "provider_id": "alpha",
                        "careers_urls": ["https://alpha.example/jobs"],
                        "extraction_mode": "snapshot_json",
                        "snapshot_path": "data/alpha.json",
                        "enabled": True,
                    },
                    {
                        "provider_id": "beta",
                        "careers_urls": ["https://beta.example/jobs"],
                        "extraction_mode": "snapshot_json",
                        "snapshot_path": "data/beta.json",
                        "enabled": False,
                    },
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    providers = load_providers_config(providers_config)
    assert resolve_provider_ids("all", providers) == ["alpha", "zeta"]


def test_run_daily_report_includes_provider_list_and_extraction_mode(tmp_path: Path, monkeypatch: Any) -> None:
    data_dir = tmp_path / "data"
    state_dir = tmp_path / "state"
    data_dir.mkdir()
    state_dir.mkdir()

    (data_dir / "candidate_profile.json").write_text(
        json.dumps({"skills": [], "roles": []}),
        encoding="utf-8",
    )

    alpha_snapshot = tmp_path / "alpha.json"
    beta_snapshot = tmp_path / "beta.json"
    alpha_snapshot.write_text(json.dumps([_raw_job("Alpha Role", "https://alpha.example/job1")]), encoding="utf-8")
    beta_snapshot.write_text(json.dumps([_raw_job("Beta Role", "https://beta.example/job2")]), encoding="utf-8")

    gamma_snapshot = tmp_path / "gamma.json"
    gamma_snapshot.write_text(json.dumps([_raw_job("Gamma Role", "https://gamma.example/job3")]), encoding="utf-8")

    providers_config = tmp_path / "providers.json"
    providers_config.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "providers": [
                    {
                        "provider_id": "gamma",
                        "careers_urls": ["https://gamma.example/jobs"],
                        "extraction_mode": "snapshot_json",
                        "mode": "snapshot",
                        "snapshot_path": str(gamma_snapshot),
                        "enabled": False,
                    },
                    {
                        "provider_id": "beta",
                        "careers_urls": ["https://beta.example/jobs"],
                        "extraction_mode": "snapshot_json",
                        "mode": "snapshot",
                        "snapshot_path": str(beta_snapshot),
                        "enabled": True,
                    },
                    {
                        "provider_id": "alpha",
                        "careers_urls": ["https://alpha.example/jobs"],
                        "extraction_mode": "snapshot_json",
                        "mode": "snapshot",
                        "snapshot_path": str(alpha_snapshot),
                        "enabled": True,
                    },
                ],
            },
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
            "--offline",
            "--snapshot-only",
            "--profiles",
            "cs",
            "--providers",
            "all",
            "--providers-config",
            str(providers_config),
        ],
    )

    rc = run_daily.main()
    assert rc == 0

    run_dirs = sorted(path for path in (state_dir / "runs").iterdir() if (path / "run_report.json").exists())
    assert run_dirs
    report = json.loads((run_dirs[-1] / "run_report.json").read_text(encoding="utf-8"))
    assert isinstance(report.get("run_id"), str)
    assert report["run_id"]

    # Disabled providers are excluded, and provider order is stable by provider_id.
    assert report["providers"] == ["alpha", "beta"]
    provenance = report["provenance_by_provider"]
    assert sorted(provenance.keys()) == report["providers"]
    for provider_id in report["providers"]:
        assert isinstance(provenance[provider_id].get("extraction_mode"), str)
        assert provenance[provider_id]["extraction_mode"].strip()


def test_run_daily_uses_jobintel_run_id_env_exactly(tmp_path: Path, monkeypatch: Any) -> None:
    data_dir = tmp_path / "data"
    state_dir = tmp_path / "state"
    data_dir.mkdir()
    state_dir.mkdir()

    (data_dir / "candidate_profile.json").write_text(
        json.dumps({"skills": [], "roles": []}),
        encoding="utf-8",
    )

    alpha_snapshot = tmp_path / "alpha.json"
    alpha_snapshot.write_text(json.dumps([_raw_job("Alpha Role", "https://alpha.example/job1")]), encoding="utf-8")

    providers_config = tmp_path / "providers.json"
    providers_config.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "providers": [
                    {
                        "provider_id": "alpha",
                        "careers_urls": ["https://alpha.example/jobs"],
                        "extraction_mode": "snapshot_json",
                        "mode": "snapshot",
                        "snapshot_path": str(alpha_snapshot),
                        "enabled": True,
                    }
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("JOBINTEL_DATA_DIR", str(data_dir))
    monkeypatch.setenv("JOBINTEL_STATE_DIR", str(state_dir))
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "")
    monkeypatch.setenv("JOBINTEL_RUN_ID", "m5-proof-custom-run-id")

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
            "--offline",
            "--snapshot-only",
            "--profiles",
            "cs",
            "--providers",
            "alpha",
            "--providers-config",
            str(providers_config),
        ],
    )

    rc = run_daily.main()
    assert rc == 0
    report_paths = sorted((state_dir / "runs").glob("*/run_report.json"))
    assert report_paths
    report = json.loads(report_paths[-1].read_text(encoding="utf-8"))
    assert report["run_id"] == "m5-proof-custom-run-id"
