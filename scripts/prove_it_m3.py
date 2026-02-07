#!/usr/bin/env python3
from __future__ import annotations

try:
    import _bootstrap  # type: ignore
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

import argparse
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict

from ji_engine.proof.bundle import (
    assert_no_secrets,
    build_excerpt_log,
    write_bundle_manifest,
    write_bundle_readme,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, check=False, text=True, capture_output=True)


def _parse_kv_stdout(stdout: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for line in stdout.splitlines():
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def _git_sha() -> str:
    result = _run(["git", "rev-parse", "--short", "HEAD"])
    if result.returncode == 0:
        return result.stdout.strip()
    return "unknown"


def _copy(src: Path, dst: Path) -> Path:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return dst


def _plan(args: argparse.Namespace) -> int:
    print("prove_it_mode=plan")
    print("expected_outputs=")
    print("  - ops/proof/bundles/m3-<run_id>/liveproof-<run_id>.log")
    print("  - ops/proof/bundles/m3-<run_id>/verify_published_s3-<run_id>.log")
    print("  - ops/proof/bundles/m3-<run_id>/proofs/<run_id>.json")
    print("  - ops/proof/bundles/m3-<run_id>/bundle_manifest.json")
    print("  - ops/proof/bundles/m3-<run_id>/README.md")
    if args.write_excerpt:
        print("  - ops/proof/bundles/m3-<run_id>/liveproof-<run_id>.excerpt.log")
    print("underlying_command=")
    print(
        " ".join(
            [
                sys.executable,
                "scripts/prove_eks_live_run.py",
                "--cluster-name",
                args.cluster_name,
                "--context",
                args.context,
                "--namespace",
                args.namespace,
                "--bucket",
                args.bucket,
                "--prefix",
                args.prefix,
                "--providers",
                args.providers,
                "--timeout",
                args.timeout,
                "--hold-seconds",
                str(args.hold_seconds),
                *([] if not args.image else ["--image", args.image]),
            ]
        )
    )
    return 0


def _run_live(args: argparse.Namespace) -> int:
    cmd = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "prove_eks_live_run.py"),
        "--cluster-name",
        args.cluster_name,
        "--context",
        args.context,
        "--namespace",
        args.namespace,
        "--bucket",
        args.bucket,
        "--prefix",
        args.prefix,
        "--providers",
        args.providers,
        "--timeout",
        args.timeout,
        "--hold-seconds",
        str(args.hold_seconds),
        *([] if not args.image else ["--image", args.image]),
    ]

    result = _run(cmd)
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, file=sys.stderr, end="")
    if result.returncode != 0:
        return result.returncode

    payload = _parse_kv_stdout(result.stdout)
    run_id = payload.get("JOBINTEL_RUN_ID")
    liveproof_log = payload.get("liveproof_log")
    proof_json = payload.get("proof_json")
    verify_log = payload.get("verify_log")
    if not (run_id and liveproof_log and proof_json and verify_log):
        print("ERROR: prove_eks_live_run did not return expected receipt paths", file=sys.stderr)
        return 2

    src_live = Path(liveproof_log)
    src_proof = Path(proof_json)
    src_verify = Path(verify_log)
    for path in (src_live, src_proof, src_verify):
        if not path.exists():
            print(f"ERROR: expected receipt file missing: {path}", file=sys.stderr)
            return 2

    for path in (src_live, src_proof, src_verify):
        text = path.read_text(encoding="utf-8", errors="replace")
        try:
            assert_no_secrets(path, text, allow_secrets=args.allow_secrets)
        except ValueError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2

    bundle_dir = REPO_ROOT / "ops" / "proof" / "bundles" / f"m3-{run_id}"
    if bundle_dir.exists():
        shutil.rmtree(bundle_dir)
    bundle_dir.mkdir(parents=True, exist_ok=True)

    b_live = _copy(src_live, bundle_dir / src_live.name)
    b_verify = _copy(src_verify, bundle_dir / src_verify.name)
    b_proof = _copy(src_proof, bundle_dir / "proofs" / src_proof.name)
    copied = [b_live, b_verify, b_proof]

    if args.write_excerpt:
        excerpt = build_excerpt_log(src_live.read_text(encoding="utf-8", errors="replace"))
        excerpt_path = bundle_dir / f"liveproof-{run_id}.excerpt.log"
        excerpt_path.write_text(excerpt, encoding="utf-8")
        copied.append(excerpt_path)

    git_sha = _git_sha()
    readme_path = write_bundle_readme(
        bundle_dir,
        run_id=run_id,
        cluster_name=args.cluster_name,
        kube_context=args.context,
        bucket=args.bucket,
        prefix=args.prefix,
        git_sha=git_sha,
    )
    copied.append(readme_path)
    manifest_path = write_bundle_manifest(
        bundle_dir,
        run_id=run_id,
        cluster_name=args.cluster_name,
        kube_context=args.context,
        bucket=args.bucket,
        prefix=args.prefix,
        git_sha=git_sha,
        files=copied,
    )

    print(f"bundle_dir={bundle_dir}")
    print(f"bundle_manifest={manifest_path}")
    print("prove_it_status=ok")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Milestone 3 prove-it wrapper (bundle + redaction guard).")
    parser.add_argument("--cluster-name", required=True)
    parser.add_argument("--context", required=True)
    parser.add_argument("--namespace", default="jobintel")
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--prefix", default="jobintel")
    parser.add_argument("--providers", default="openai", help="Comma-separated providers for run_daily.")
    parser.add_argument("--timeout", default="20m")
    parser.add_argument("--hold-seconds", type=int, default=45)
    parser.add_argument("--image", default=None, help="Optional image override for the one-off proof job.")
    parser.add_argument("--plan", action="store_true", help="Print deterministic outputs and underlying command.")
    parser.add_argument("--allow-secrets", action="store_true", help="Allow secret-like strings in logs/json.")
    parser.add_argument(
        "--write-excerpt",
        action="store_true",
        help="Write a commit-safe excerpt log with sensitive patterns redacted.",
    )
    args = parser.parse_args(argv)

    if args.plan:
        return _plan(args)
    return _run_live(args)


if __name__ == "__main__":
    raise SystemExit(main())
