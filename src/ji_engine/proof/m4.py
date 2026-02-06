from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ji_engine.proof.bundle import sha256_file


@dataclass(frozen=True)
class M4PlanConfig:
    run_id: str
    namespace: str
    onprem_overlay: str
    backup_uri: str
    aws_region: str
    backup_bucket: str
    backup_prefix: str
    dr_tf_dir: str
    execute: bool


def render_onprem_plan(config: M4PlanConfig) -> str:
    mode = "execute" if config.execute else "plan"
    lines = [
        f"mode={mode}",
        f"run_id={config.run_id}",
        "step=onprem_deploy",
        f"namespace={config.namespace}",
        f"overlay={config.onprem_overlay}",
        "commands:",
        f"  python scripts/k8s_render.py --overlay {config.onprem_overlay} > /tmp/jobintel-{config.run_id}.yaml",
        f"  kubectl -n {config.namespace} diff -f /tmp/jobintel-{config.run_id}.yaml",
        f"  kubectl -n {config.namespace} apply -f /tmp/jobintel-{config.run_id}.yaml",
    ]
    return "\n".join(lines) + "\n"


def build_backup_plan(config: M4PlanConfig) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "mode": "execute" if config.execute else "plan",
        "run_id": config.run_id,
        "backup_uri": config.backup_uri,
        "aws_region": config.aws_region,
        "required_objects": [
            f"{config.backup_prefix}/metadata.json",
            f"{config.backup_prefix}/state.tar.zst",
            f"{config.backup_prefix}/manifests.tar.zst",
        ],
        "commands": [
            f"scripts/ops/dr_restore.sh --backup-uri {config.backup_uri}",
        ],
    }


def render_dr_plan(config: M4PlanConfig) -> str:
    lines = [
        f"mode={'execute' if config.execute else 'plan'}",
        f"run_id={config.run_id}",
        "step=dr_rehearsal",
        f"terraform_dir={config.dr_tf_dir}",
        "commands:",
        "  APPLY=0 scripts/ops/dr_bringup.sh",
        f"  scripts/ops/dr_restore.sh --backup-uri {config.backup_uri}",
        "  RUN_JOB=1 scripts/ops/dr_validate.sh",
        "  CONFIRM_DESTROY=1 scripts/ops/dr_teardown.sh",
    ]
    return "\n".join(lines) + "\n"


def write_m4_bundle(
    output_root: Path,
    *,
    config: M4PlanConfig,
    onprem_plan: str,
    backup_plan: dict[str, Any],
    dr_plan: str,
) -> Path:
    bundle_dir = output_root / f"m4-{config.run_id}"
    bundle_dir.mkdir(parents=True, exist_ok=True)

    onprem_plan_path = bundle_dir / "onprem_plan.txt"
    backup_plan_path = bundle_dir / "backup_plan.json"
    dr_plan_path = bundle_dir / "dr_plan.txt"

    onprem_plan_path.write_text(onprem_plan, encoding="utf-8")
    backup_plan_path.write_text(
        json.dumps(backup_plan, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    dr_plan_path.write_text(dr_plan, encoding="utf-8")

    files = [onprem_plan_path, backup_plan_path, dr_plan_path]
    manifest = {
        "schema_version": 1,
        "run_id": config.run_id,
        "mode": "execute" if config.execute else "plan",
        "files": [
            {
                "path": path.relative_to(bundle_dir).as_posix(),
                "sha256": sha256_file(path),
                "size_bytes": path.stat().st_size,
            }
            for path in sorted(files)
        ],
    }
    manifest_path = bundle_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return bundle_dir
