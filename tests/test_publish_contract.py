import json
from pathlib import Path

import scripts.run_daily as run_daily


def _write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj), encoding="utf-8")


def test_publish_contract_failure_marks_run_failed(tmp_path: Path) -> None:
    run_meta = tmp_path / "run_report.json"
    _write_json(run_meta, {"run_id": "r1", "status": "success", "success": True})

    publish_section = {
        "enabled": True,
        "required": True,
        "bucket": "bucket",
        "prefix": "jobintel",
        "pointer_write": {"global": "error", "provider_profile": {"openai:cs": "error"}, "error": "denied"},
    }

    assert run_daily._publish_contract_failed(publish_section) is True
    run_daily._update_run_metadata_publish(
        run_meta,
        publish_section,
        success_override=False,
        status_override="failed",
    )

    data = json.loads(run_meta.read_text(encoding="utf-8"))
    assert data["publish"]["pointer_write"]["global"] == "error"
    assert data["success"] is False
    assert data["status"] == "failed"
