import importlib
import json

import ji_engine.config as config
import scripts.run_daily as run_daily_module


def test_write_proof_receipt(tmp_path, monkeypatch) -> None:
    state_dir = tmp_path / "state"
    monkeypatch.setenv("JOBINTEL_STATE_DIR", str(state_dir))
    importlib.reload(config)
    run_daily = importlib.reload(run_daily_module)

    run_report = {
        "run_id": "2026-01-02T00:00:00Z",
        "timestamp": "2026-01-02T00:01:02Z",
        "status": "success",
        "providers": ["openai"],
        "profiles": ["cs"],
        "provenance_by_provider": {
            "openai": {
                "scrape_mode": "live",
                "live_attempted": True,
                "live_result": "success",
                "snapshot_used": False,
                "parsed_job_count": 12,
            }
        },
    }
    publish_section = {
        "enabled": True,
        "required": True,
        "bucket": "proof-bucket",
        "prefix": "jobintel",
        "pointer_write": {
            "global": "ok",
            "provider_profile": {"openai:cs": "ok"},
            "error": None,
        },
    }
    s3_meta = {"status": "ok", "reason": None}

    proof_path = run_daily._write_proof_receipt(
        tmp_path / "run_report.json",
        run_report,
        s3_meta=s3_meta,
        publish_section=publish_section,
    )

    assert proof_path is not None
    assert proof_path.exists()
    payload = json.loads(proof_path.read_text(encoding="utf-8"))
    assert payload["run_id"] == "2026-01-02T00:00:00Z"
    assert payload["publish"]["pointer_global"] == "ok"
    assert payload["provenance"]["openai"]["scrape_mode"] == "live"
