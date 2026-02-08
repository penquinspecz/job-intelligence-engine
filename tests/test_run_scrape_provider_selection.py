from __future__ import annotations

import json
from pathlib import Path

import pytest

import scripts.run_scrape as run_scrape


def test_run_scrape_unknown_provider_fails_closed_with_exit_2(tmp_path: Path) -> None:
    providers_path = tmp_path / "providers.json"
    providers_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "providers": [
                    {
                        "provider_id": "alpha",
                        "careers_urls": ["https://alpha.example/jobs"],
                        "extraction_mode": "snapshot_json",
                        "snapshot_path": "data/alpha.json",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(SystemExit) as exc:
        run_scrape.main(["--providers", "alpha,missing", "--providers-config", str(providers_path)])
    assert exc.value.code == 2
