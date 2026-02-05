from __future__ import annotations

from pathlib import Path

import yaml


def test_cronjob_does_not_mount_app_data_root() -> None:
    manifest = Path("ops/k8s/jobintel/cronjob.yaml").read_text(encoding="utf-8")
    doc = yaml.safe_load(manifest)
    container = doc["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"][0]
    mounts = container.get("volumeMounts", [])
    mount_paths = [m.get("mountPath") for m in mounts]
    assert "/app/data" not in mount_paths
    assert "/app/data/ashby_cache" in mount_paths
