from __future__ import annotations

import importlib
import json
from pathlib import Path

import scripts.run_scrape as run_scrape


def test_run_scrape_jsonld_snapshot_provider(tmp_path, monkeypatch) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    snapshot_dir = data_dir / "xai_snapshots"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    (snapshot_dir / "index.html").write_text(
        Path("tests/fixtures/providers/xai/index.html").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    providers_path = tmp_path / "providers.json"
    providers_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "providers": [
                    {
                        "provider_id": "xai",
                        "name": "xAI",
                        "careers_urls": ["https://x.ai/careers"],
                        "extraction_mode": "jsonld",
                        "mode": "snapshot",
                        "snapshot_path": str(snapshot_dir / "index.html"),
                        "live_enabled": False,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("JOBINTEL_DATA_DIR", str(data_dir))
    import ji_engine.config as config

    importlib.reload(config)
    importlib.reload(run_scrape)

    rc = run_scrape.main(["--providers", "xai", "--providers-config", str(providers_path)])
    assert rc == 0

    output_dir = data_dir / "ashby_cache"
    raw_path = output_dir / "xai_raw_jobs.json"
    assert raw_path.exists()
    jobs = json.loads(raw_path.read_text(encoding="utf-8"))
    assert [job.get("apply_url") for job in jobs] == [
        "https://x.ai/careers/ml-inference-engineer",
        "https://x.ai/careers/sre-platform",
    ]


def test_run_scrape_jsonld_snapshot_provider_perplexity(tmp_path, monkeypatch) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    snapshot_dir = data_dir / "perplexity_snapshots"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    (snapshot_dir / "index.html").write_text(
        "\n".join(
            [
                "<!doctype html>",
                "<html>",
                "  <head>",
                '    <meta charset="utf-8" />',
                "    <title>Perplexity Careers Fixture</title>",
                "  </head>",
                "  <body>",
                "    <h1>Perplexity Careers</h1>",
                '    <script type="application/ld+json">',
                "      [",
                "        {",
                '          "@context": "https://schema.org",',
                '          "@type": "JobPosting",',
                '          "title": "Forward Deployed Engineer",',
                '          "url": "https://www.perplexity.ai/careers/forward-deployed-engineer",',
                '          "hiringOrganization": {"@type": "Organization", "name": "Perplexity"},',
                '          "jobLocation": {',
                '            "@type": "Place",',
                '            "address": {',
                '              "@type": "PostalAddress",',
                '              "addressLocality": "San Francisco",',
                '              "addressRegion": "CA",',
                '              "addressCountry": "US"',
                "            }",
                "          }",
                "        },",
                "        {",
                '          "@context": "https://schema.org",',
                '          "@type": "JobPosting",',
                '          "title": "Machine Learning Engineer",',
                '          "url": "https://www.perplexity.ai/careers/machine-learning-engineer",',
                '          "hiringOrganization": {"@type": "Organization", "name": "Perplexity"},',
                '          "jobLocation": {',
                '            "@type": "Place",',
                '            "address": {',
                '              "@type": "PostalAddress",',
                '              "addressLocality": "San Francisco",',
                '              "addressRegion": "CA",',
                '              "addressCountry": "US"',
                "            }",
                "          }",
                "        }",
                "      ]",
                "    </script>",
                "    <p>Deterministic fixture for JSON-LD scraping tests.</p>",
                "  </body>",
                "</html>",
                "",
            ]
        ),
        encoding="utf-8",
    )

    providers_path = tmp_path / "providers.json"
    providers_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "providers": [
                    {
                        "provider_id": "perplexity",
                        "name": "Perplexity",
                        "careers_urls": ["https://www.perplexity.ai/careers"],
                        "extraction_mode": "jsonld",
                        "mode": "snapshot",
                        "snapshot_path": str(snapshot_dir / "index.html"),
                        "live_enabled": False,
                        "politeness": {
                            "defaults": {"max_qps": 1.0, "max_attempts": 2},
                            "host_overrides": {"www.perplexity.ai": {"max_qps": 0.5, "max_inflight_per_host": 1}},
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("JOBINTEL_DATA_DIR", str(data_dir))
    import ji_engine.config as config

    importlib.reload(config)
    importlib.reload(run_scrape)

    rc = run_scrape.main(["--providers", "perplexity", "--providers-config", str(providers_path)])
    assert rc == 0

    output_dir = data_dir / "ashby_cache"
    raw_path = output_dir / "perplexity_raw_jobs.json"
    assert raw_path.exists()
    jobs = json.loads(raw_path.read_text(encoding="utf-8"))
    assert [job.get("apply_url") for job in jobs] == [
        "https://www.perplexity.ai/careers/forward-deployed-engineer",
        "https://www.perplexity.ai/careers/machine-learning-engineer",
    ]
