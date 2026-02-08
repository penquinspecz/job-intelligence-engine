#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from ji_engine.proof.bundle import redact_text, sha256_file  # noqa: E402
from ji_engine.proof.politeness_proof import (  # noqa: E402
    extract_event_lines,
    extract_provenance_payloads,
    provider_payload,
    required_politeness_issues,
)
from ji_engine.utils.time import utc_now, utc_now_z  # noqa: E402


def _utc_now() -> datetime:
    return utc_now()


def _utc_now_iso() -> str:
    return utc_now_z(seconds_precision=True)


def _run_id_default() -> str:
    return utc_now_z(seconds_precision=True)


def _run(cmd: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, check=False, cwd=str(cwd or REPO_ROOT), capture_output=True, text=True)


def _fmt_cmd(cmd: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in cmd)


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_redacted(path: Path, text: str) -> None:
    path.write_text(redact_text(text), encoding="utf-8")


def _write_manifest(proof_dir: Path, *, run_id: str) -> Path:
    files = [p for p in sorted(proof_dir.glob("*")) if p.is_file() and p.name != "manifest.json"]
    payload = {
        "schema_version": 1,
        "run_id": run_id,
        "files": [
            {"path": file_path.name, "sha256": sha256_file(file_path), "size_bytes": file_path.stat().st_size}
            for file_path in files
        ],
    }
    path = proof_dir / "manifest.json"
    _write_json(path, payload)
    return path


def _kubectl_base(context: str | None, namespace: str) -> list[str]:
    cmd = ["kubectl"]
    if context:
        cmd.extend(["--context", context])
    cmd.extend(["-n", namespace])
    return cmd


def _run_checked(cmd: list[str]) -> str:
    result = _run(cmd)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(f"command failed ({result.returncode}): {_fmt_cmd(cmd)} :: {detail}")
    return result.stdout


def _resolve_context(explicit_context: str | None) -> str | None:
    if explicit_context:
        return explicit_context
    result = _run(["kubectl", "config", "current-context"])
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    return value or None


def _wait_for_pod(context: str | None, namespace: str, job_name: str) -> str:
    deadline = time.time() + 180
    while time.time() < deadline:
        result = _run(
            _kubectl_base(context, namespace)
            + [
                "get",
                "pods",
                "-l",
                f"job-name={job_name}",
                "--sort-by=.metadata.creationTimestamp",
                "-o",
                "custom-columns=NAME:.metadata.name",
                "--no-headers",
            ]
        )
        if result.returncode == 0:
            lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
            if lines:
                return lines[-1]
        time.sleep(2)
    raise RuntimeError(f"pod for job {job_name} not found")


def _wait_for_job_terminal(context: str | None, namespace: str, job_name: str, timeout_s: int) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        output = _run_checked(_kubectl_base(context, namespace) + ["get", "job", job_name, "-o", "json"])
        payload = json.loads(output)
        status = payload.get("status", {}) if isinstance(payload, dict) else {}
        if int(status.get("succeeded", 0) or 0) > 0:
            return
        if int(status.get("failed", 0) or 0) > 0:
            raise RuntimeError(f"job {job_name} failed")
        time.sleep(2)
    raise RuntimeError(f"timed out waiting for job {job_name}")


def _build_plan_payload(
    *,
    run_id: str,
    captured_at: str,
    namespace: str,
    context: str | None,
    template: Path,
    provider_id: str,
    output_dir: Path,
) -> dict:
    return {
        "schema_version": 1,
        "mode": "plan",
        "run_id": run_id,
        "captured_at": captured_at,
        "namespace": namespace,
        "k8s_context": context or "<current-context>",
        "template": str(template),
        "provider_id": provider_id,
        "output_dir": str(output_dir),
        "commands": [
            f"kubectl -n {namespace} apply -f {template}",
            f"kubectl -n {namespace} wait --for=condition=complete job/<generated-name> --timeout=10m",
            f"kubectl -n {namespace} logs job/<generated-name>",
        ],
        "required_log_markers": [
            "[provider_retry][backoff]",
            "[provider_retry][circuit_breaker]",
            "[provider_retry][robots]",
            "[run_scrape][provenance]",
        ],
        "expected_files": [
            "run.log",
            "provenance.json",
            "receipt.json",
            "manifest.json",
        ],
    }


def _excerpt_log(log_text: str) -> str:
    patterns = (
        "[provider_retry][backoff]",
        "[provider_retry][circuit_breaker]",
        "[provider_retry][robots]",
        "[run_scrape][provenance]",
        "[run_scrape][POLICY_SUMMARY]",
    )
    lines = [line for line in log_text.splitlines() if any(pattern in line for pattern in patterns)]
    return "\n".join(lines) + ("\n" if lines else "")


def _capture_plan(
    *,
    proof_dir: Path,
    run_id: str,
    captured_at: str,
    namespace: str,
    context: str | None,
    template: Path,
    provider_id: str,
) -> dict:
    plan = _build_plan_payload(
        run_id=run_id,
        captured_at=captured_at,
        namespace=namespace,
        context=context,
        template=template,
        provider_id=provider_id,
        output_dir=proof_dir,
    )
    plan_text = json.dumps(plan, indent=2, sort_keys=True) + "\n"
    _write_redacted(proof_dir / "run.log", plan_text)
    _write_json(proof_dir / "provenance.json", {"mode": "plan", "provider_id": provider_id, "run_id": run_id})
    receipt = {
        "schema_version": 1,
        "mode": "plan",
        "run_id": run_id,
        "captured_at": captured_at,
        "namespace": namespace,
        "k8s_context": context,
        "provider_id": provider_id,
        "evidence_files": ["run.log", "provenance.json"],
    }
    _write_json(proof_dir / "receipt.json", receipt)
    _write_manifest(proof_dir, run_id=run_id)
    return receipt


def _capture_execute(
    *,
    proof_dir: Path,
    run_id: str,
    captured_at: str,
    namespace: str,
    explicit_context: str | None,
    template: Path,
    provider_id: str,
    timeout: str,
) -> dict:
    context = _resolve_context(explicit_context)
    job_name = "jobintel-politeness-proof"
    _run_checked(_kubectl_base(context, namespace) + ["delete", "job", job_name, "--ignore-not-found=true"])
    _run_checked(_kubectl_base(context, namespace) + ["apply", "-f", str(template)])
    timeout_s = int(timeout[:-1]) * 60 if timeout.endswith("m") else int(timeout[:-1]) if timeout.endswith("s") else 600
    _wait_for_job_terminal(context, namespace, job_name, timeout_s)
    pod_name = _wait_for_pod(context, namespace, job_name)
    logs = _run_checked(_kubectl_base(context, namespace) + ["logs", f"job/{job_name}"])

    issues = required_politeness_issues(log_text=logs, provider_id=provider_id)
    if issues:
        raise RuntimeError("politeness proof validation failed: " + "; ".join(issues))

    events = extract_event_lines(logs)
    payload = None
    for candidate_raw in extract_provenance_payloads(logs):
        candidate = provider_payload(candidate_raw, provider_id)
        if candidate is not None:
            payload = candidate
            break
    if payload is None:
        raise RuntimeError(f"missing provider payload for {provider_id}")

    _write_redacted(proof_dir / "run.log", _excerpt_log(logs))
    provenance_doc = {
        "provider_id": provider_id,
        "event_counts": {
            "backoff": len(events["backoff"]),
            "circuit_breaker": len(events["circuit_breaker"]),
            "robots": len(events["robots"]),
        },
        "payload": payload,
    }
    _write_json(proof_dir / "provenance.json", provenance_doc)

    receipt = {
        "schema_version": 1,
        "mode": "execute",
        "run_id": run_id,
        "captured_at": captured_at,
        "namespace": namespace,
        "k8s_context": context,
        "job_name": job_name,
        "pod_name": pod_name,
        "provider_id": provider_id,
        "assertions": {
            "backoff_events": len(events["backoff"]) > 0,
            "circuit_breaker_events": len(events["circuit_breaker"]) > 0,
            "robots_events": len(events["robots"]) > 0,
            "provenance_present": True,
        },
        "evidence_files": ["run.log", "provenance.json"],
    }
    _write_json(proof_dir / "receipt.json", receipt)
    _write_manifest(proof_dir, run_id=run_id)
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Capture M3 in-cluster politeness proof receipts (backoff + circuit breaker) in plan-first mode."
    )
    parser.add_argument("--run-id", default="")
    parser.add_argument("--output-dir", default="ops/proof/bundles")
    parser.add_argument("--cluster-context", default="")
    parser.add_argument("--namespace", default="jobintel")
    parser.add_argument(
        "--template",
        default="ops/k8s/jobintel/jobs/jobintel-politeness-proof.job.yaml",
        help="Path to the one-off politeness proof job manifest.",
    )
    parser.add_argument("--provider-id", default="proof_backoff")
    parser.add_argument("--timeout", default="10m")
    parser.add_argument("--execute", action="store_true", help="Run in-cluster proof collection.")
    parser.add_argument("--plan", action="store_true", help="Explicit no-op mode (default behavior).")
    parser.add_argument("--captured-at", default="", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    run_id = args.run_id or _run_id_default()
    captured_at = args.captured_at or _utc_now_iso()
    proof_dir = (REPO_ROOT / args.output_dir / f"m3-{run_id}" / "politeness").resolve()
    proof_dir.mkdir(parents=True, exist_ok=True)
    template = (REPO_ROOT / args.template).resolve()

    try:
        if args.execute:
            receipt = _capture_execute(
                proof_dir=proof_dir,
                run_id=run_id,
                captured_at=captured_at,
                namespace=args.namespace,
                explicit_context=args.cluster_context or None,
                template=template,
                provider_id=args.provider_id,
                timeout=args.timeout,
            )
            status = "executed"
        else:
            receipt = _capture_plan(
                proof_dir=proof_dir,
                run_id=run_id,
                captured_at=captured_at,
                namespace=args.namespace,
                context=args.cluster_context or None,
                template=template,
                provider_id=args.provider_id,
            )
            status = "planned"
    except Exception as exc:
        print(f"prove_m3_backoff_cb_status=failed error={exc!r}")
        return 2

    print(f"prove_m3_backoff_cb_mode={receipt['mode']}")
    print(f"prove_m3_backoff_cb_run_id={run_id}")
    print(f"prove_m3_backoff_cb_bundle={proof_dir}")
    print(f"prove_m3_backoff_cb_receipt={proof_dir / 'receipt.json'}")
    print(f"prove_m3_backoff_cb_manifest={proof_dir / 'manifest.json'}")
    print(f"prove_m3_backoff_cb_status={status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
