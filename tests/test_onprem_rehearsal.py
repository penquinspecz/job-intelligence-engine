from __future__ import annotations

import subprocess

import pytest

from scripts import onprem_rehearsal


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


def test_onprem_rehearsal_dry_run_output_is_stable(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest = _manifest_with_required_resources()

    def fake_run(cmd: list[str], cwd=onprem_rehearsal.REPO_ROOT):
        if cmd[:2] == ["make", "doctor"]:
            return _cp(0, stdout="doctor pass\n")
        if len(cmd) >= 2 and cmd[1].endswith("scripts/k8s_render.py"):
            return _cp(0, stdout=manifest)
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(onprem_rehearsal, "_run", fake_run)
    monkeypatch.setenv("DRY_RUN", "1")

    rc = onprem_rehearsal.main([])
    assert rc == 0

    out = capsys.readouterr().out
    assert "[onprem-rehearsal] doctor: running" in out
    assert "[onprem-rehearsal] doctor: pass" in out
    assert "[onprem-rehearsal] resources: pass (8 objects)" in out
    assert "kubectl apply -k ops/k8s/overlays/onprem-pi" in out
    assert "[onprem-rehearsal] DRY_RUN=1 (no apply executed)" in out


def test_onprem_rehearsal_fails_when_required_resource_missing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest = """apiVersion: v1
kind: Namespace
metadata:
  name: jobintel
"""

    def fake_run(cmd: list[str], cwd=onprem_rehearsal.REPO_ROOT):
        if cmd[:2] == ["make", "doctor"]:
            return _cp(0, stdout="doctor pass\n")
        if len(cmd) >= 2 and cmd[1].endswith("scripts/k8s_render.py"):
            return _cp(0, stdout=manifest)
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(onprem_rehearsal, "_run", fake_run)
    rc = onprem_rehearsal.main([])
    assert rc == 1

    err = capsys.readouterr().err
    assert "missing required resources" in err
