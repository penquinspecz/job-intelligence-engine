from __future__ import annotations

from pathlib import Path

import yaml


def _load_manifest(path: Path) -> dict:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def test_job_once_manifest_has_required_contracts() -> None:
    manifest = _load_manifest(Path("ops/k8s/job.once.yaml"))
    assert manifest.get("kind") == "Job"
    spec = manifest.get("spec", {})
    template = spec.get("template", {})
    pod_spec = template.get("spec", {})
    security = pod_spec.get("securityContext", {})
    assert security.get("runAsNonRoot") is True
    assert security.get("runAsUser") == 1000
    assert security.get("runAsGroup") == 1000
    containers = pod_spec.get("containers", [])
    assert containers
    container = containers[0]
    csec = container.get("securityContext", {})
    assert csec.get("readOnlyRootFilesystem") is True
    args = "\n".join(container.get("args", []))
    assert "--snapshot-only" in args
    assert "--offline" in args
    assert "publish_s3.py --run-dir" in args
    assert "--plan --json" in args
    assert "replay_run.py --run-dir" in args
    assert "--strict --json" in args
    mounts = container.get("volumeMounts", [])
    mount_paths = [m.get("mountPath") for m in mounts]
    assert "/app/data" in mount_paths
    assert "/app/state" in mount_paths
    assert not any("snapshots" in (p or "") for p in mount_paths)


def test_cronjob_manifest_has_offline_snapshot_flags() -> None:
    manifest = _load_manifest(Path("ops/k8s/cronjob.yaml"))
    assert manifest.get("kind") == "CronJob"
    spec = manifest.get("spec", {})
    template = spec.get("jobTemplate", {}).get("spec", {}).get("template", {})
    pod_spec = template.get("spec", {})
    security = pod_spec.get("securityContext", {})
    assert security.get("runAsNonRoot") is True
    assert security.get("runAsUser") == 1000
    assert security.get("runAsGroup") == 1000
    containers = pod_spec.get("containers", [])
    assert containers
    container = containers[0]
    csec = container.get("securityContext", {})
    assert csec.get("readOnlyRootFilesystem") is True
    args = "\n".join(container.get("args", []))
    assert "--snapshot-only" in args
    assert "--offline" in args
