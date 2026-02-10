import importlib
import json

import scripts.run_scrape as run_scrape


def test_run_scrape_multiple_providers_snapshot(tmp_path, monkeypatch) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    alpha_snapshot = data_dir / "alpha.json"
    beta_snapshot = data_dir / "beta.json"

    alpha_snapshot.write_text(
        json.dumps(
            [
                {"title": "B Job", "apply_url": "https://example.com/b"},
                {"title": "A Job", "apply_url": "https://example.com/a"},
            ]
        ),
        encoding="utf-8",
    )
    beta_snapshot.write_text(
        json.dumps(
            [
                {"title": "Z Job", "apply_url": "https://example.com/z"},
                {"title": "Y Job", "apply_url": "https://example.com/y"},
            ]
        ),
        encoding="utf-8",
    )

    providers_path = tmp_path / "providers.json"
    providers_path.write_text(
        json.dumps(
            [
                {
                    "provider_id": "alpha",
                    "careers_url": "https://example.com/alpha",
                    "extraction_mode": "snapshot_json",
                    "mode": "snapshot",
                    "snapshot_path": str(alpha_snapshot),
                },
                {
                    "provider_id": "beta",
                    "careers_url": "https://example.com/beta",
                    "extraction_mode": "snapshot_json",
                    "mode": "snapshot",
                    "snapshot_path": str(beta_snapshot),
                },
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("JOBINTEL_DATA_DIR", str(data_dir))
    import ji_engine.config as config

    importlib.reload(config)
    importlib.reload(run_scrape)

    rc = run_scrape.main(
        [
            "--providers",
            "alpha,beta",
            "--providers-config",
            str(providers_path),
        ]
    )
    assert rc == 0

    output_dir = data_dir / "ashby_cache"
    alpha_out = output_dir / "alpha_raw_jobs.json"
    beta_out = output_dir / "beta_raw_jobs.json"
    assert alpha_out.exists()
    assert beta_out.exists()

    alpha_jobs = json.loads(alpha_out.read_text(encoding="utf-8"))
    assert [j.get("apply_url") for j in alpha_jobs] == [
        "https://example.com/a",
        "https://example.com/b",
    ]
