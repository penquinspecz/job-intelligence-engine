#!/usr/bin/env python3
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    import _bootstrap  # type: ignore
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

import importlib.util


def _load_publish_s3():
    spec = importlib.util.spec_from_file_location("publish_s3", Path(__file__).with_name("publish_s3.py"))
    if not spec or not spec.loader:
        raise RuntimeError("publish_s3 module not found")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(cmd: list[str], env: dict[str, str]) -> None:
    result = subprocess.run(cmd, env=env, cwd=Path(__file__).resolve().parents[1])
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def main() -> int:
    base_dir = Path(tempfile.mkdtemp(prefix="jobintel_ecs_shape_"))
    data_dir = base_dir / "data"
    state_dir = base_dir / "state"
    data_dir.mkdir(parents=True, exist_ok=True)
    state_dir.mkdir(parents=True, exist_ok=True)

    run_id = "2026-01-01T00:00:00Z"
    env = os.environ.copy()
    env.update(
        {
            "JOBINTEL_DATA_DIR": str(data_dir),
            "JOBINTEL_STATE_DIR": str(state_dir),
            "JOBINTEL_CRONJOB_RUN_ID": run_id,
            "CAREERS_MODE": "SNAPSHOT",
            "EMBED_PROVIDER": "stub",
            "ENRICH_MAX_WORKERS": "1",
            "DISCORD_WEBHOOK_URL": "",
            "AWS_REGION": "us-east-1",
            "AWS_ACCESS_KEY_ID": "ecs-shape-smoke",
            "AWS_SECRET_ACCESS_KEY": "ecs-shape-smoke",
        }
    )

    try:
        publish_s3 = _load_publish_s3()
        cronjob_proc = subprocess.run(
            [sys.executable, "scripts/cronjob_simulate.py"],
            env=env,
            cwd=Path(__file__).resolve().parents[1],
            check=False,
        )

        run_dir = state_dir / "runs" / publish_s3._sanitize_run_id(run_id)
        report_path = run_dir / "run_report.json"
        if cronjob_proc.returncode != 0:
            if not report_path.exists():
                raise SystemExit(cronjob_proc.returncode)
            print(
                f"ecs_shape_smoke: cronjob_simulate exited {cronjob_proc.returncode}, continuing with replay",
                file=sys.stderr,
            )
        plan_path = state_dir / "publish_plan.json"

        plan_cmd = [
            sys.executable,
            "scripts/publish_s3.py",
            "--run-dir",
            str(run_dir),
            "--plan",
            "--json",
            "--bucket",
            "dummy-bucket",
            "--prefix",
            "jobintel",
        ]
        plan_result = subprocess.run(
            plan_cmd,
            env=env,
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            check=False,
        )
        if plan_result.returncode != 0:
            if plan_result.stderr:
                sys.stderr.write(plan_result.stderr.decode("utf-8", errors="replace"))
            raise SystemExit(plan_result.returncode)
        plan_path.write_bytes(plan_result.stdout)

        _run(
            [
                sys.executable,
                "scripts/verify_published_s3.py",
                "--offline",
                "--plan-json",
                str(plan_path),
                "--bucket",
                "dummy-bucket",
                "--run-id",
                run_id,
                "--run-dir",
                str(run_dir),
            ],
            env,
        )

        _run(
            [
                sys.executable,
                "scripts/replay_run.py",
                "--run-dir",
                str(run_dir),
                "--profile",
                "cs",
                "--strict",
            ],
            env,
        )
        return 0
    finally:
        shutil.rmtree(base_dir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
