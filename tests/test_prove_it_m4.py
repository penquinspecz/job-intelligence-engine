from __future__ import annotations

import json
from pathlib import Path

from ji_engine.proof.m4 import (
    M4PlanConfig,
    build_backup_plan,
    render_dr_plan,
    render_onprem_plan,
    write_m4_bundle,
)


def _cfg(*, run_id: str = "run-fixed", execute: bool = False) -> M4PlanConfig:
    return M4PlanConfig(
        run_id=run_id,
        namespace="jobintel",
        onprem_overlay="onprem",
        backup_uri="s3://bucket/jobintel/backups/run-fixed",
        aws_region="us-east-1",
        backup_bucket="bucket",
        backup_prefix="jobintel/backups/run-fixed",
        dr_tf_dir="ops/dr/terraform",
        execute=execute,
    )


def test_m4_plan_renderers_are_deterministic() -> None:
    config = _cfg()

    onprem_1 = render_onprem_plan(config)
    onprem_2 = render_onprem_plan(config)
    assert onprem_1 == onprem_2
    assert "mode=plan" in onprem_1

    dr_1 = render_dr_plan(config)
    dr_2 = render_dr_plan(config)
    assert dr_1 == dr_2
    assert "scripts/ops/dr_bringup.sh" in dr_1

    backup_1 = build_backup_plan(config)
    backup_2 = build_backup_plan(config)
    assert backup_1 == backup_2
    assert backup_1["run_id"] == "run-fixed"


def test_write_m4_bundle_creates_expected_files_and_manifest(tmp_path: Path) -> None:
    config = _cfg(run_id="run-123")
    bundle_dir = write_m4_bundle(
        tmp_path,
        config=config,
        onprem_plan=render_onprem_plan(config),
        backup_plan=build_backup_plan(config),
        dr_plan=render_dr_plan(config),
    )

    assert bundle_dir == tmp_path / "m4-run-123"
    assert (bundle_dir / "onprem_plan.txt").exists()
    assert (bundle_dir / "backup_plan.json").exists()
    assert (bundle_dir / "dr_plan.txt").exists()
    assert (bundle_dir / "manifest.json").exists()

    manifest = json.loads((bundle_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["schema_version"] == 1
    assert manifest["run_id"] == "run-123"
    assert manifest["mode"] == "plan"
    assert [item["path"] for item in manifest["files"]] == [
        "backup_plan.json",
        "dr_plan.txt",
        "onprem_plan.txt",
    ]
    for item in manifest["files"]:
        assert len(item["sha256"]) == 64
        assert item["size_bytes"] > 0
