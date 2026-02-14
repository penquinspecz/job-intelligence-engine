from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from scripts import onprem_rehearsal
from scripts.schema_validate import resolve_named_schema_path, validate_payload


def _cp(returncode: int = 0, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=["cmd"], returncode=returncode, stdout=stdout, stderr=stderr)


def _manifest_with_required_resources() -> str:
    return """apiVersion: v1
kind: Namespace
metadata:
  name: jobintel
---
apiVersion: batch/v1
kind: CronJob
metadata:
  name: jobintel-daily
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: jobintel-dashboard
---
apiVersion: v1
kind: Service
metadata:
  name: jobintel-dashboard
---
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: jobintel-dashboard
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: jobintel-data-pvc
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: jobintel-state-pvc
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: dashboard-ingress-baseline
"""


def _set_fake_runner(monkeypatch: pytest.MonkeyPatch, manifest: str) -> None:
    def fake_run(cmd: list[str], *, cwd: Path):
        if cmd[:2] == ["make", "doctor"]:
            return _cp(0, stdout="doctor pass\n")
        if cmd[:3] == ["git", "rev-parse", "HEAD"]:
            return _cp(0, stdout="deadbeefdeadbeefdeadbeefdeadbeefdeadbeef\n")
        if len(cmd) >= 2 and cmd[1] == "scripts/k8s_render.py":
            return _cp(0, stdout=manifest)
        if cmd[:3] == ["kubectl", "apply", "-k"]:
            return _cp(0, stdout="applied\n")
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(onprem_rehearsal, "_run", fake_run)


def _validate_receipt(payload: dict[str, object]) -> None:
    schema_path = resolve_named_schema_path("onprem_rehearsal_receipt", 1)
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    errors = validate_payload(payload, schema)
    assert errors == [], f"schema errors: {errors}"


def test_no_receipt_written_by_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _set_fake_runner(monkeypatch, _manifest_with_required_resources())
    monkeypatch.setattr(onprem_rehearsal, "STATE_DIR", tmp_path / "state")
    monkeypatch.delenv("WRITE_RECEIPT", raising=False)

    rc = onprem_rehearsal.main(["--run-id", "20260214T120000Z"])
    assert rc == 0
    receipt = tmp_path / "state" / "rehearsals" / "20260214T120000Z" / "onprem_rehearsal_receipt.v1.json"
    assert not receipt.exists()


def test_receipt_schema_valid_when_enabled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _set_fake_runner(monkeypatch, _manifest_with_required_resources())
    monkeypatch.setattr(onprem_rehearsal, "STATE_DIR", tmp_path / "state")
    monkeypatch.setenv("WRITE_RECEIPT", "1")

    rc = onprem_rehearsal.main(["--run-id", "20260214T120000Z"])
    assert rc == 0

    receipt = tmp_path / "state" / "rehearsals" / "20260214T120000Z" / "onprem_rehearsal_receipt.v1.json"
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    _validate_receipt(payload)
    assert payload["status"] == "success"
    assert payload["failure_code"] is None


def test_rehearsal_output_prints_receipt_and_next_steps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    _set_fake_runner(monkeypatch, _manifest_with_required_resources())
    monkeypatch.setattr(onprem_rehearsal, "STATE_DIR", tmp_path / "state")
    monkeypatch.setenv("WRITE_RECEIPT", "1")

    rc = onprem_rehearsal.main(["--run-id", "20260214T120000Z"])
    assert rc == 0

    out = capsys.readouterr().out
    lines = [line for line in out.splitlines() if line]
    assert any(line.startswith("REHEARSAL_RECEIPT_PATH=") for line in lines)
    assert "NEXT_STEPS_BEGIN" in lines
    assert "1) kubectl apply -k ops/k8s/overlays/onprem-pi" in lines
    assert "2) kubectl get pods -n jobintel -o wide" in lines
    assert "3) See ingress/dashboard notes: ops/onprem/RUNBOOK_DEPLOY.md" in lines
    assert "NEXT_STEPS_END" in lines
    # Bounded output: keep UX compact and deterministic.
    assert len(lines) <= 30


def test_receipt_stable_across_runs_with_same_input(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _set_fake_runner(monkeypatch, _manifest_with_required_resources())
    monkeypatch.setattr(onprem_rehearsal, "STATE_DIR", tmp_path / "state")
    monkeypatch.setenv("WRITE_RECEIPT", "1")
    run_id = "20260214T120000Z"

    first = onprem_rehearsal.main(["--run-id", run_id])
    assert first == 0
    receipt = tmp_path / "state" / "rehearsals" / run_id / "onprem_rehearsal_receipt.v1.json"
    first_bytes = receipt.read_bytes()

    second = onprem_rehearsal.main(["--run-id", run_id])
    assert second == 0
    second_bytes = receipt.read_bytes()

    assert second_bytes == first_bytes


def test_receipt_failure_code_when_required_resources_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bad_manifest = """apiVersion: v1
kind: Namespace
metadata:
  name: jobintel
"""
    _set_fake_runner(monkeypatch, bad_manifest)
    monkeypatch.setattr(onprem_rehearsal, "STATE_DIR", tmp_path / "state")
    monkeypatch.setenv("WRITE_RECEIPT", "1")

    rc = onprem_rehearsal.main(["--run-id", "20260214T130000Z"])
    assert rc == 1

    receipt = tmp_path / "state" / "rehearsals" / "20260214T130000Z" / "onprem_rehearsal_receipt.v1.json"
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    _validate_receipt(payload)
    assert payload["status"] == "failed"
    assert payload["failure_code"] == "OVERLAY_RESOURCES_MISSING"


def test_optional_run_index_integration_when_db_exists(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _set_fake_runner(monkeypatch, _manifest_with_required_resources())
    monkeypatch.setattr(onprem_rehearsal, "STATE_DIR", tmp_path / "state")
    monkeypatch.setenv("WRITE_RECEIPT", "1")
    monkeypatch.setattr(onprem_rehearsal, "RUN_INDEX_PATH", tmp_path / "state" / "run_index.sqlite3")
    onprem_rehearsal.RUN_INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    onprem_rehearsal.RUN_INDEX_PATH.write_bytes(b"")

    rc = onprem_rehearsal.main(["--run-id", "20260214T120000Z"])
    assert rc == 0

    import sqlite3

    conn = sqlite3.connect(onprem_rehearsal.RUN_INDEX_PATH)
    try:
        row = conn.execute(
            "SELECT run_id, status, receipt_path FROM onprem_rehearsal_index_v1 WHERE run_id = ?",
            ("20260214T120000Z",),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    assert row[0] == "20260214T120000Z"
    assert row[1] == "success"
    assert isinstance(row[2], str) and row[2].endswith("onprem_rehearsal_receipt.v1.json")
