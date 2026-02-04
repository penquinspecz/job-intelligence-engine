from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")


def test_proof_run_extract_outputs_expected_lines(tmp_path: Path) -> None:
    run_report = {
        "run_id": "run_123",
        "verifiable_artifacts": {"output:ranked_json": {"path": "ranked.json", "sha256": "abc", "bytes": 123}},
        "config_fingerprint": "deadbeef",
        "environment_fingerprint": "cafebabe",
        "replay_verification": {"ok": True, "checked": 1, "mismatched": 0, "missing": 0},
    }
    plan_doc = {
        "plan": [
            {"s3_key": "runs/run_123/ranked.json", "sha256": "abc", "bytes": 123},
            {"s3_key": "runs/run_123/shortlist.md", "sha256": "", "bytes": None},
        ]
    }

    run_report_path = tmp_path / "run_report.json"
    plan_path = tmp_path / "plan.json"
    _write_json(run_report_path, run_report)
    _write_json(plan_path, plan_doc)

    result = subprocess.run(
        [
            sys.executable,
            "scripts/proof_run_extract.py",
            "--run-report",
            str(run_report_path),
            "--plan-json",
            str(plan_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    output = result.stdout
    assert "run_id: run_123" in output
    assert "verifiable_artifacts: 1" in output
    assert "config_fingerprint: deadbeef" in output
    assert "environment_fingerprint: cafebabe" in output
    assert "plan_items: 2" in output
    assert "plan_missing_sha_or_bytes: 1" in output
    assert "replay_ok: true" in output
