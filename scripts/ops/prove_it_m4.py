#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from ji_engine.proof.m4 import (  # noqa: E402
    M4PlanConfig,
    build_backup_plan,
    render_dr_plan,
    render_onprem_plan,
    write_m4_bundle,
)
from ji_engine.utils.time import utc_now  # noqa: E402


def _utc_compact() -> str:
    return utc_now().strftime("%Y%m%dT%H%M%SZ")


def _run(cmd: list[str], *, env: dict[str, str] | None = None) -> int:
    merged_env = None
    if env is not None:
        merged_env = os.environ.copy()
        merged_env.update(env)
    result = subprocess.run(cmd, check=False, cwd=str(REPO_ROOT), env=merged_env)
    return result.returncode


def _require_execute_arg(value: str | None, name: str) -> str:
    if value:
        return value
    raise SystemExit(f"--execute requires {name}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Milestone 4 prove-it planner/executor with deterministic receipts.")
    parser.add_argument("--plan", action="store_true", default=False, help="Plan mode (default when --execute unset).")
    parser.add_argument("--execute", action="store_true", help="Run commands (disabled by default).")
    parser.add_argument("--output-dir", default="ops/proof/bundles", help="Output directory for proof bundles.")
    parser.add_argument("--run-id", default="", help="Optional run id override. Default: UTC timestamp.")
    parser.add_argument("--namespace", default="jobintel")
    parser.add_argument("--onprem-overlay", default="onprem")
    parser.add_argument("--backup-uri", default="", help="S3 backup URI required for DR restore validation.")
    parser.add_argument("--aws-region", default="")
    parser.add_argument("--backup-bucket", default="")
    parser.add_argument("--backup-prefix", default="")
    args = parser.parse_args(argv)

    execute = bool(args.execute)
    run_id = args.run_id or _utc_compact()
    backup_uri = args.backup_uri or "s3://<bucket>/<prefix>/backups/<backup_id>"
    aws_region = args.aws_region or "<aws-region>"
    backup_bucket = args.backup_bucket or "<backup-bucket>"
    backup_prefix = args.backup_prefix or "<backup-prefix>/backups/<backup_id>"

    config = M4PlanConfig(
        run_id=run_id,
        namespace=args.namespace,
        onprem_overlay=args.onprem_overlay,
        backup_uri=backup_uri,
        aws_region=aws_region,
        backup_bucket=backup_bucket,
        backup_prefix=backup_prefix,
        dr_tf_dir="ops/dr/terraform",
        execute=execute,
    )
    onprem_plan = render_onprem_plan(config)
    backup_plan = build_backup_plan(config)
    dr_plan = render_dr_plan(config)

    output_root = Path(args.output_dir)
    bundle_dir = write_m4_bundle(
        output_root,
        config=config,
        onprem_plan=onprem_plan,
        backup_plan=backup_plan,
        dr_plan=dr_plan,
    )

    print(f"prove_it_m4_mode={'execute' if execute else 'plan'}")
    print(f"prove_it_m4_run_id={run_id}")
    print(f"prove_it_m4_bundle={bundle_dir}")
    print("prove_it_m4_receipts=")
    print(f"  - {bundle_dir / 'onprem_plan.txt'}")
    print(f"  - {bundle_dir / 'backup_plan.json'}")
    print(f"  - {bundle_dir / 'dr_plan.txt'}")
    print(f"  - {bundle_dir / 'manifest.json'}")

    if not execute:
        print("prove_it_m4_status=planned")
        return 0

    backup_uri_execute = _require_execute_arg(args.backup_uri, "--backup-uri")
    if not args.aws_region:
        _require_execute_arg(args.aws_region, "--aws-region")
    if not args.backup_bucket:
        _require_execute_arg(args.backup_bucket, "--backup-bucket")
    if not args.backup_prefix:
        _require_execute_arg(args.backup_prefix, "--backup-prefix")

    rendered_path = Path("/tmp") / f"jobintel-{run_id}.yaml"
    render_cmd = [
        sys.executable,
        "scripts/k8s_render.py",
        "--overlay",
        args.onprem_overlay,
    ]
    with rendered_path.open("w", encoding="utf-8") as f:
        result = subprocess.run(render_cmd, cwd=str(REPO_ROOT), check=False, text=True, stdout=f)
    if result.returncode != 0:
        return result.returncode

    for cmd in (
        ["kubectl", "-n", args.namespace, "diff", "-f", str(rendered_path)],
        ["kubectl", "-n", args.namespace, "apply", "-f", str(rendered_path)],
    ):
        rc = _run(cmd)
        if rc != 0:
            return rc

    for cmd, env_overrides in (
        (["scripts/ops/dr_bringup.sh"], {"APPLY": "1"}),
        (["scripts/ops/dr_restore.sh", "--backup-uri", backup_uri_execute], None),
        (["scripts/ops/dr_validate.sh"], {"RUN_JOB": "1"}),
        (["scripts/ops/dr_teardown.sh"], {"CONFIRM_DESTROY": "1"}),
    ):
        rc = _run(cmd, env=env_overrides)
        if rc != 0:
            return rc

    print("prove_it_m4_status=executed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
