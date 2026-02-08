#!/usr/bin/env python3
from __future__ import annotations

try:
    import _bootstrap  # type: ignore
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

from ji_engine.proof.liveproof import (
    build_liveproof_capture,
    extract_provenance_line,
    extract_provenance_payload,
    extract_publish_markers,
    extract_run_id,
    required_provenance_issues,
)
from ji_engine.utils.time import utc_now

REPO_ROOT = Path(__file__).resolve().parents[1]


def _utc_stamp() -> str:
    return utc_now().strftime("%Y%m%d%H%M%S")


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, check=False, text=True, capture_output=True)


def _run_with_input(cmd: list[str], payload: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, input=payload, check=False, text=True, capture_output=True)


def _kubectl_cmd(context: Optional[str], *args: str) -> list[str]:
    cmd = ["kubectl"]
    if context:
        cmd.extend(["--context", context])
    cmd.extend(args)
    return cmd


def _run_checked(cmd: list[str], *, step: str) -> str:
    result = _run(cmd)
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "command failed"
        raise RuntimeError(f"{step} failed: {detail}")
    return result.stdout


def _parse_namespace(args: argparse.Namespace) -> str:
    return args.namespace.strip()


def _create_job_from_template(
    context: Optional[str],
    namespace: str,
    job_name: str,
    *,
    image: Optional[str] = None,
    providers: str = "openai",
    hold_seconds: int = 45,
) -> None:
    template_path = REPO_ROOT / "ops" / "k8s" / "jobintel" / "jobs" / "jobintel-liveproof.job.yaml"
    render_cmd = _kubectl_cmd(
        context,
        "create",
        "-f",
        str(template_path),
        "--dry-run=client",
        "-o",
        "json",
    )
    rendered = _run_checked(render_cmd, step="render liveproof template")
    payload = json.loads(rendered)
    if not isinstance(payload, dict):
        raise RuntimeError("invalid liveproof template payload")
    payload.setdefault("metadata", {})
    payload["metadata"]["name"] = job_name
    payload["metadata"]["namespace"] = namespace
    containers = payload.get("spec", {}).get("template", {}).get("spec", {}).get("containers", [])
    if not (isinstance(containers, list) and containers and isinstance(containers[0], dict)):
        raise RuntimeError("invalid liveproof template containers payload")
    container = containers[0]
    if image:
        container["image"] = image
    cmd = (
        f"python scripts/run_daily.py --profiles cs --providers {providers} --us_only --no_post; "
        f"rc=$?; sleep {max(0, hold_seconds)}; exit $rc"
    )
    container["command"] = ["/bin/sh", "-lc"]
    container["args"] = [cmd]

    env = container.get("env")
    if not isinstance(env, list):
        env = []
        container["env"] = env

    def _upsert_env(name: str, value: str) -> None:
        for item in env:
            if isinstance(item, dict) and item.get("name") == name:
                item["value"] = value
                return
        env.append({"name": name, "value": value})

    _upsert_env("CAREERS_MODE", "LIVE")
    _upsert_env("JOBINTEL_WRITE_PROOF", "1")
    _upsert_env("PUBLISH_S3", "1")
    _upsert_env("PUBLISH_S3_DRY_RUN", "0")
    _upsert_env("PUBLISH_S3_REQUIRE", "1")
    apply_cmd = _kubectl_cmd(context, "apply", "-f", "-")
    apply_result = _run_with_input(apply_cmd, json.dumps(payload))
    if apply_result.returncode != 0:
        detail = apply_result.stderr.strip() or apply_result.stdout.strip() or "command failed"
        raise RuntimeError(f"create liveproof job from template failed: {detail}")


def _copy_proof_json(context: Optional[str], namespace: str, pod_name: str, run_id: str) -> Path:
    local = REPO_ROOT / "state" / "proofs" / f"{run_id}.json"
    local.parent.mkdir(parents=True, exist_ok=True)
    remote_path = f"/app/state/proofs/{run_id}.json"
    deadline = time.time() + 300
    while time.time() < deadline:
        cmd = _kubectl_cmd(context, "-n", namespace, "exec", pod_name, "--", "cat", remote_path)
        result = _run(cmd)
        if result.returncode == 0 and result.stdout.strip():
            local.write_text(result.stdout, encoding="utf-8")
            return local
        detail = (result.stderr or result.stdout).strip()
        if "cannot exec into a container in a completed pod" in detail:
            break
        time.sleep(2)
    raise RuntimeError(f"proof json unavailable in running pod: {remote_path}")
    return local


def _copy_run_report(context: Optional[str], namespace: str, pod_name: str, run_id: str) -> Path:
    find_cmd = _kubectl_cmd(
        context,
        "-n",
        namespace,
        "exec",
        pod_name,
        "--",
        "sh",
        "-lc",
        (
            "for f in /app/state/runs/*/run_report.json; do "
            '[ -f "$f" ] || continue; '
            f'grep -q \'{run_id}\' "$f" && echo "$f" && exit 0; '
            "done; exit 1"
        ),
    )
    run_report_remote = _run_checked(find_cmd, step="locate run report").strip()
    run_dir_name = Path(run_report_remote).parent.name
    local_run_dir = REPO_ROOT / "state" / "runs" / run_dir_name
    local_run_dir.mkdir(parents=True, exist_ok=True)
    payload = _run_checked(
        _kubectl_cmd(context, "-n", namespace, "exec", pod_name, "--", "cat", run_report_remote),
        step="copy run report",
    )
    (local_run_dir / "run_report.json").write_text(payload, encoding="utf-8")
    return local_run_dir


def _write_liveproof_log(run_id: str, logs: str, provenance_line: str, publish_line: str) -> Path:
    path = REPO_ROOT / "ops" / "proof" / f"liveproof-{run_id}.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    tail = "\n".join(logs.splitlines()[-120:])
    payload = [
        f"JOBINTEL_RUN_ID={run_id}",
        f"[run_scrape][provenance] {provenance_line}",
        publish_line,
        "",
        "--- LOG TAIL ---",
        tail,
        "",
    ]
    path.write_text("\n".join(payload), encoding="utf-8")
    return path


def _write_verify_log(run_id: str, verify_cmd: list[str], verify_result: subprocess.CompletedProcess[str]) -> Path:
    path = REPO_ROOT / "ops" / "proof" / f"verify_published_s3-{run_id}.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(
        [
            f"command: {' '.join(verify_cmd)}",
            f"exit_code: {verify_result.returncode}",
            "--- stdout ---",
            verify_result.stdout,
            "--- stderr ---",
            verify_result.stderr,
            "",
        ]
    )
    path.write_text(text, encoding="utf-8")
    return path


def _extract_publish_line(logs: str) -> str:
    for line in reversed(logs.splitlines()):
        if "PUBLISH_CONTRACT " in line:
            return line
    return ""


def _normalize_provenance_payload(provenance_payload: dict[str, object]) -> dict[str, object]:
    # Older/live images can emit provider-scoped provenance like {"openai": {...}}.
    # Normalize to a single provider payload, but fail closed if ambiguous.
    if "live_attempted" in provenance_payload or "scrape_mode" in provenance_payload:
        return provenance_payload

    candidates: list[dict[str, object]] = []
    for value in provenance_payload.values():
        if not isinstance(value, dict):
            continue
        if "live_attempted" in value or "scrape_mode" in value:
            candidates.append(value)
    if len(candidates) == 1:
        return candidates[0]
    return provenance_payload


def _wait_for_pod_name(context: Optional[str], namespace: str, job_name: str) -> str:
    deadline = time.time() + 120
    while time.time() < deadline:
        result = _run(
            _kubectl_cmd(
                context,
                "-n",
                namespace,
                "get",
                "pods",
                "-l",
                f"job-name={job_name}",
                "-o",
                "jsonpath={.items[0].metadata.name}",
            )
        )
        name = (result.stdout or "").strip()
        if result.returncode == 0 and name:
            return name
        time.sleep(2)
    raise RuntimeError("resolve pod name failed: pod not found")


def _wait_for_run_id(context: Optional[str], namespace: str, job_name: str) -> str:
    deadline = time.time() + 180
    while time.time() < deadline:
        result = _run(_kubectl_cmd(context, "-n", namespace, "logs", f"job/{job_name}"))
        if result.returncode == 0:
            run_id = extract_run_id(result.stdout)
            if run_id:
                return run_id
        time.sleep(2)
    raise RuntimeError("missing JOBINTEL_RUN_ID in logs")


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run one-off EKS liveproof job and capture deterministic receipts.")
    parser.add_argument("--cluster-name", required=True)
    parser.add_argument("--namespace", default="jobintel")
    parser.add_argument("--context", default=None)
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--prefix", default="jobintel")
    parser.add_argument("--timeout", default="20m")
    parser.add_argument("--image", default=None, help="Optional image override for the one-off job container.")
    parser.add_argument("--providers", default="openai", help="Comma-separated providers for run_daily.")
    parser.add_argument(
        "--hold-seconds", type=int, default=45, help="Seconds to sleep after run_daily for receipt copy."
    )
    args = parser.parse_args(argv)

    namespace = _parse_namespace(args)
    ts = _utc_stamp()
    job_name = f"jobintel-liveproof-{ts}"

    try:
        _create_job_from_template(
            args.context,
            namespace,
            job_name,
            image=args.image,
            providers=args.providers,
            hold_seconds=args.hold_seconds,
        )

        pod_name = _wait_for_pod_name(args.context, namespace, job_name)
        early_run_id = _wait_for_run_id(args.context, namespace, job_name)
        proof_json_path = _copy_proof_json(args.context, namespace, pod_name, early_run_id)
        run_dir_path = _copy_run_report(args.context, namespace, pod_name, early_run_id)

        wait_cmd = _kubectl_cmd(
            args.context,
            "-n",
            namespace,
            "wait",
            "--for=condition=complete",
            f"job/{job_name}",
            f"--timeout={args.timeout}",
        )
        _run_checked(wait_cmd, step="wait for completion")

        image = _run_checked(
            _kubectl_cmd(
                args.context,
                "-n",
                namespace,
                "get",
                "pod",
                pod_name,
                "-o",
                "jsonpath={.spec.containers[0].image}",
            ),
            step="resolve pod image",
        ).strip()
        logs = _run_checked(_kubectl_cmd(args.context, "-n", namespace, "logs", f"job/{job_name}"), step="fetch logs")

        run_id = extract_run_id(logs)
        if not run_id:
            raise RuntimeError("missing JOBINTEL_RUN_ID in logs")
        if run_id != early_run_id:
            raise RuntimeError("run_id mismatch between early logs and final logs")
        provenance_payload = extract_provenance_payload(logs)
        provenance_line = extract_provenance_line(logs)
        if not provenance_payload or not provenance_line:
            raise RuntimeError("missing [run_scrape][provenance] JSON line in logs")
        normalized_provenance = _normalize_provenance_payload(provenance_payload)
        issues = required_provenance_issues(normalized_provenance)
        if issues:
            raise RuntimeError("; ".join(issues))
        publish_markers = extract_publish_markers(logs)
        if publish_markers.get("s3_status") != "ok":
            raise RuntimeError("missing s3_status=ok in logs")
        if publish_markers.get("pointer_global") != "ok":
            raise RuntimeError("missing pointer_global=ok in logs")
        publish_line = _extract_publish_line(logs)
        if not publish_line:
            raise RuntimeError("missing PUBLISH_CONTRACT log line")

        liveproof_log_path = _write_liveproof_log(run_id, logs, provenance_line, publish_line)
        verify_cmd = [
            sys.executable,
            str(REPO_ROOT / "scripts" / "verify_published_s3.py"),
            "--bucket",
            args.bucket,
            "--run-id",
            run_id,
            "--prefix",
            args.prefix,
            "--run-dir",
            str(run_dir_path),
            "--verify-latest",
        ]
        verify_result = _run(verify_cmd)
        verify_log_path = _write_verify_log(run_id, verify_cmd, verify_result)
        if verify_result.returncode != 0:
            raise RuntimeError("verify_published_s3 failed")

        base_payload = json.loads(proof_json_path.read_text(encoding="utf-8"))
        if not isinstance(base_payload, dict):
            raise RuntimeError("proof json from pod is not an object")
        base_payload["liveproof_capture"] = build_liveproof_capture(
            run_id=run_id,
            cluster_name=args.cluster_name,
            namespace=namespace,
            job_name=job_name,
            pod_name=pod_name,
            image=image,
            bucket=args.bucket,
            prefix=args.prefix,
            verify_exit_code=verify_result.returncode,
            verify_log_path=str(verify_log_path),
            liveproof_log_path=str(liveproof_log_path),
            provenance=normalized_provenance,
            publish_markers=publish_markers,
        )
        proof_json_path.write_text(
            json.dumps(base_payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )

        print(f"job_name={job_name}")
        print(f"pod_name={pod_name}")
        print(f"image={image}")
        print(f"JOBINTEL_RUN_ID={run_id}")
        print(f"liveproof_log={liveproof_log_path}")
        print(f"proof_json={proof_json_path}")
        print(f"verify_log={verify_log_path}")
        print("liveproof_status=ok")
        return 0
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
