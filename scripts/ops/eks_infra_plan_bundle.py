#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from ji_engine.proof.bundle import redact_text, sha256_file  # noqa: E402
from ji_engine.utils.time import utc_now_z  # noqa: E402


def _utc_now_iso() -> str:
    return utc_now_z(seconds_precision=True)


def _env_with_aws(*, aws_profile: str, aws_region: str) -> dict[str, str]:
    env = dict(os.environ)
    env["AWS_PROFILE"] = aws_profile
    env["AWS_REGION"] = aws_region
    env.setdefault("AWS_DEFAULT_REGION", aws_region)
    env["AWS_EC2_METADATA_DISABLED"] = "true"
    return env


def _run(cmd: list[str], *, env: dict[str, str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        check=False,
        capture_output=True,
        text=True,
        cwd=str(cwd or REPO_ROOT),
        env=env,
    )


def _fmt_cmd(cmd: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in cmd)


def _write_text(path: Path, text: str, *, redact: bool = False) -> None:
    payload = redact_text(text) if redact else text
    path.write_text(payload, encoding="utf-8")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _record_command(
    path: Path, *, cmd: list[str], result: subprocess.CompletedProcess[str], redact: bool = False
) -> None:
    rendered = [f"$ {_fmt_cmd(cmd)}", ""]
    if result.stdout:
        rendered.append(result.stdout.rstrip())
    if result.stderr:
        rendered.append(result.stderr.rstrip())
    rendered.append("")
    _write_text(path, "\n".join(rendered), redact=redact)


def _run_checked(
    *,
    cmd: list[str],
    env: dict[str, str],
    out_path: Path,
    redact: bool = False,
    cwd: Path | None = None,
    error_hint: str,
) -> subprocess.CompletedProcess[str]:
    result = _run(cmd, env=env, cwd=cwd)
    _record_command(out_path, cmd=cmd, result=result, redact=redact)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(f"{error_hint}: command failed ({result.returncode}) {_fmt_cmd(cmd)} :: {detail}")
    return result


def _write_manifest(bundle_dir: Path, *, run_id: str) -> Path:
    files = [p for p in sorted(bundle_dir.glob("*")) if p.is_file() and p.name != "manifest.json"]
    manifest = {
        "schema_version": 1,
        "run_id": run_id,
        "files": [{"path": p.name, "sha256": sha256_file(p), "size_bytes": p.stat().st_size} for p in files],
    }
    path = bundle_dir / "manifest.json"
    _write_json(path, manifest)
    return path


def _cluster_exists(*, cluster_name: str, aws_region: str, env: dict[str, str], bundle_dir: Path) -> bool:
    cmd = ["aws", "eks", "describe-cluster", "--name", cluster_name, "--region", aws_region, "--output", "json"]
    out_path = bundle_dir / "aws_eks_describe_cluster.log"
    result = _run(cmd, env=env)
    _record_command(out_path, cmd=cmd, result=result, redact=True)
    if result.returncode != 0:
        detail = ((result.stderr or "") + "\n" + (result.stdout or "")).lower()
        if "resourcenotfoundexception" in detail or "resource not found" in detail:
            return False
        raise RuntimeError(
            f"aws eks describe-cluster failed: {(result.stderr or result.stdout).strip() or 'unknown error'}"
        )

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        raise RuntimeError("aws eks describe-cluster returned non-json output")

    _write_json(bundle_dir / "aws_eks_describe_cluster.json", payload)
    return True


def _state_list(*, tf_bin: str, tf_dir: Path, env: dict[str, str], bundle_dir: Path) -> tuple[bool, bool, list[str]]:
    cmd = [tf_bin, f"-chdir={tf_dir}", "state", "list"]
    result = _run(cmd, env=env)
    _record_command(bundle_dir / "tofu_state_list.log", cmd=cmd, result=result, redact=True)

    if result.returncode != 0:
        return True, False, []
    entries = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    has_cluster = "aws_eks_cluster.this" in entries
    return len(entries) == 0, has_cluster, entries


def _validate_profile(expected_profile: str) -> None:
    actual = os.environ.get("AWS_PROFILE", "").strip()
    if not actual:
        raise RuntimeError(f"AWS_PROFILE is required and must be '{expected_profile}'")
    if actual != expected_profile:
        raise RuntimeError(f"AWS_PROFILE mismatch: expected '{expected_profile}', got '{actual}'")


def _check_root_identity(*, aws_region: str, env: dict[str, str], bundle_dir: Path) -> None:
    cmd = ["aws", "sts", "get-caller-identity", "--region", aws_region, "--output", "json"]
    result = _run_checked(
        cmd=cmd,
        env=env,
        out_path=bundle_dir / "aws_sts_get_caller_identity.log",
        redact=True,
        error_hint="aws identity check failed",
    )
    payload = json.loads(result.stdout)
    _write_json(bundle_dir / "aws_sts_get_caller_identity.json", payload)
    arn = str(payload.get("Arn", ""))
    if arn.endswith(":root"):
        raise RuntimeError(f"refusing to continue with root identity: {arn}")


def _next_failure_command(*, args: argparse.Namespace) -> str:
    return (
        f"AWS_PROFILE={args.aws_profile} AWS_REGION={args.aws_region} CLUSTER_NAME={args.cluster_name} "
        "scripts/ops/tofu_state_check.sh --print-imports"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Plan-only EKS infra bundle capture (deterministic, guardrailed).")
    parser.add_argument("--run-id", default=os.environ.get("RUN_ID", "local"))
    parser.add_argument("--output-dir", default="ops/proof/bundles")
    parser.add_argument("--cluster-name", default=os.environ.get("CLUSTER_NAME", "jobintel-eks"))
    parser.add_argument(
        "--aws-region", default=os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-east-1"
    )
    parser.add_argument("--aws-profile", default="jobintel-deployer")
    parser.add_argument("--tf-dir", default="ops/aws/infra/eks")
    parser.add_argument("--captured-at", default="", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    tf_bin = shutil.which("tofu") or "tofu"
    if not shutil.which("tofu"):
        print("eks_infra_plan_bundle_status=failed error='tofu not found'", file=sys.stderr)
        print("NEXT: brew install opentofu", file=sys.stderr)
        return 2

    tf_dir = (REPO_ROOT / args.tf_dir).resolve()
    bundle_dir = (REPO_ROOT / args.output_dir / f"m4-{args.run_id}" / "eks_infra").resolve()
    bundle_dir.mkdir(parents=True, exist_ok=True)

    receipt_path = bundle_dir / "receipt.json"
    manifest_path = bundle_dir / "manifest.json"
    captured_at = args.captured_at or _utc_now_iso()

    try:
        _validate_profile(args.aws_profile)
        env = _env_with_aws(aws_profile=args.aws_profile, aws_region=args.aws_region)

        _check_root_identity(aws_region=args.aws_region, env=env, bundle_dir=bundle_dir)
        cluster_exists = _cluster_exists(
            cluster_name=args.cluster_name,
            aws_region=args.aws_region,
            env=env,
            bundle_dir=bundle_dir,
        )

        vars_cmd = [sys.executable, "scripts/tofu_eks_vars_from_aws.py", "--cluster-name", args.cluster_name]
        vars_result = _run(vars_cmd, env=env)
        _record_command(bundle_dir / "tofu_eks_vars_from_aws.log", cmd=vars_cmd, result=vars_result, redact=True)
        if cluster_exists and vars_result.returncode != 0:
            detail = (vars_result.stderr or vars_result.stdout).strip()
            raise RuntimeError(f"tofu var generation failed: {detail}")

        _run_checked(
            cmd=[tf_bin, f"-chdir={tf_dir}", "version"],
            env=env,
            out_path=bundle_dir / "tofu_version.log",
            error_hint="tofu version failed",
        )
        _run_checked(
            cmd=[tf_bin, f"-chdir={tf_dir}", "providers"],
            env=env,
            out_path=bundle_dir / "tofu_providers.log",
            error_hint="tofu providers failed",
        )
        _run_checked(
            cmd=[tf_bin, f"-chdir={tf_dir}", "workspace", "show"],
            env=env,
            out_path=bundle_dir / "tofu_workspace_show.log",
            error_hint="tofu workspace show failed",
        )

        state_empty, has_cluster_in_state, state_entries = _state_list(
            tf_bin=tf_bin,
            tf_dir=tf_dir,
            env=env,
            bundle_dir=bundle_dir,
        )

        if cluster_exists and state_empty:
            raise RuntimeError(
                "state is empty while EKS cluster exists. Import existing resources before plan/apply "
                "(run scripts/ops/tofu_state_check.sh --print-imports)."
            )
        if state_entries and not has_cluster_in_state:
            raise RuntimeError("state is non-empty but missing aws_eks_cluster.this (misaligned state)")

        _run_checked(
            cmd=[tf_bin, f"-chdir={tf_dir}", "fmt", "-check"],
            env=env,
            out_path=bundle_dir / "tofu_fmt.log",
            error_hint="tofu fmt failed",
        )
        _run_checked(
            cmd=[tf_bin, f"-chdir={tf_dir}", "validate"],
            env=env,
            out_path=bundle_dir / "tofu_validate.log",
            error_hint="tofu validate failed",
        )

        plan_bin = bundle_dir / "eks_infra.tfplan"
        _run_checked(
            cmd=[
                tf_bin,
                f"-chdir={tf_dir}",
                "plan",
                "-input=false",
                "-var-file=local.auto.tfvars.json",
                f"-out={plan_bin}",
            ],
            env=env,
            out_path=bundle_dir / "tofu_plan_applyable.log",
            redact=True,
            error_hint="tofu plan failed",
        )
        plan_show = _run_checked(
            cmd=[tf_bin, f"-chdir={tf_dir}", "show", "-no-color", str(plan_bin)],
            env=env,
            out_path=bundle_dir / "tofu_plan_show.log",
            redact=True,
            error_hint="tofu show failed",
        )
        _write_text(bundle_dir / "tofu_plan_sanitized.txt", plan_show.stdout, redact=True)

        receipt = {
            "schema_version": 1,
            "mode": "plan",
            "run_id": args.run_id,
            "captured_at": captured_at,
            "cluster_name": args.cluster_name,
            "aws_profile": args.aws_profile,
            "aws_region": args.aws_region,
            "cluster_exists": cluster_exists,
            "state_empty": state_empty,
            "has_cluster_in_state": has_cluster_in_state,
            "bundle_dir": str(bundle_dir),
            "plan_file": str(plan_bin),
        }
        _write_json(receipt_path, receipt)
        _write_manifest(bundle_dir, run_id=args.run_id)

    except Exception as exc:
        receipt = {
            "schema_version": 1,
            "mode": "plan",
            "run_id": args.run_id,
            "captured_at": captured_at,
            "cluster_name": args.cluster_name,
            "aws_profile": args.aws_profile,
            "aws_region": args.aws_region,
            "status": "failed",
            "error": str(exc),
            "bundle_dir": str(bundle_dir),
        }
        _write_json(receipt_path, receipt)
        _write_manifest(bundle_dir, run_id=args.run_id)
        print(f"eks_infra_plan_bundle_status=failed error={exc!r}")
        print(f"NEXT: {_next_failure_command(args=args)}")
        print(f"eks_infra_plan_bundle={bundle_dir}")
        print(f"eks_infra_plan_receipt={receipt_path}")
        print(f"eks_infra_plan_manifest={manifest_path}")
        return 2

    print("eks_infra_plan_bundle_status=planned")
    print(f"eks_infra_plan_run_id={args.run_id}")
    print(f"eks_infra_plan_bundle={bundle_dir}")
    print(f"eks_infra_plan_receipt={receipt_path}")
    print(f"eks_infra_plan_manifest={manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
