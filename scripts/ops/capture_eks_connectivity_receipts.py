#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
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


def _utc_iso() -> str:
    return utc_now_z(seconds_precision=True)


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, check=False, capture_output=True, text=True)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_readme(bundle_dir: Path) -> str:
    readme = bundle_dir / "README.md"
    _write_text(
        readme,
        "\n".join(
            [
                "# EKS Connectivity Proof Bundle (M4)",
                "",
                "Plan mode (no kubectl calls):",
                "```bash",
                "python scripts/ops/capture_eks_connectivity_receipts.py --plan \\",
                "  --run-id m4-eks-proof-20260208T072500Z \\",
                "  --output-dir ops/proof/bundles \\",
                "  --cluster-context eks-jobintel-eks \\",
                "  --namespace jobintel",
                "```",
                "",
                "Execute (capture kubectl outputs):",
                "```bash",
                "python scripts/ops/capture_eks_connectivity_receipts.py --execute \\",
                "  --run-id m4-eks-proof-20260208T072500Z \\",
                "  --output-dir ops/proof/bundles \\",
                "  --cluster-context eks-jobintel-eks \\",
                "  --namespace jobintel",
                "```",
                "",
            ]
        ),
    )
    return readme.name


def _write_capture_script(bundle_dir: Path, *, context: str, namespace: str) -> str:
    capture = bundle_dir / "capture_commands.sh"
    _write_text(
        capture,
        "\n".join(
            [
                "#!/usr/bin/env bash",
                "set -euo pipefail",
                "",
                f'CTX="{context}"',
                f'NS="{namespace}"',
                "",
                'kubectl --context "$CTX" get --raw /version',
                'kubectl --context "$CTX" get nodes -o wide',
                'kubectl --context "$CTX" -n "$NS" get pods -o wide',
                'kubectl --context "$CTX" -n "$NS" get events --sort-by=.lastTimestamp',
                "",
            ]
        ),
    )
    capture.chmod(0o755)
    return capture.name


def _write_manifest(bundle_dir: Path, *, run_id: str, evidence_files: list[str]) -> Path:
    files = sorted(
        {
            path
            for rel_path in evidence_files
            for path in [bundle_dir / rel_path]
            if path.is_file() and path.name != "manifest.json"
        },
        key=lambda p: p.as_posix(),
    )
    payload = {
        "schema_version": 1,
        "run_id": run_id,
        "files": [
            {
                "path": path.relative_to(bundle_dir).as_posix(),
                "sha256": sha256_file(path),
                "size_bytes": path.stat().st_size,
            }
            for path in files
        ],
    }
    manifest_path = bundle_dir / "manifest.json"
    _write_json(manifest_path, payload)
    return manifest_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Plan-first EKS connectivity proof bundle capture.")
    parser.add_argument("--plan", action="store_true", default=False)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--output-dir", default="ops/proof/bundles")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--cluster-context", default="eks-jobintel-eks")
    parser.add_argument("--namespace", default="jobintel")
    parser.add_argument("--captured-at", default="", help=argparse.SUPPRESS)
    parser.add_argument("--started-at", default="", help=argparse.SUPPRESS)
    parser.add_argument("--finished-at", default="", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    run_id = args.run_id or _utc_iso().replace("-", "").replace(":", "")
    mode = "execute" if args.execute else "plan"
    started_at = args.started_at or _utc_iso()
    captured_at = args.captured_at or _utc_iso()

    bundle_dir = (REPO_ROOT / args.output_dir / f"m4-{run_id}" / "eks").resolve()
    bundle_dir.mkdir(parents=True, exist_ok=True)

    files: list[str] = []
    files.append(_write_readme(bundle_dir))
    files.append(_write_capture_script(bundle_dir, context=args.cluster_context, namespace=args.namespace))

    passed = True
    if args.execute:
        version = _run(["kubectl", "--context", args.cluster_context, "get", "--raw", "/version"])
        if version.returncode != 0:
            raise RuntimeError((version.stderr or version.stdout).strip() or "kubectl /version failed")
        _write_text(bundle_dir / "version.json", redact_text(version.stdout))
        files.append("version.json")

        nodes = _run(["kubectl", "--context", args.cluster_context, "get", "nodes", "-o", "wide"])
        if nodes.returncode != 0:
            raise RuntimeError((nodes.stderr or nodes.stdout).strip() or "kubectl get nodes failed")
        _write_text(bundle_dir / "nodes_wide.log", redact_text(nodes.stdout))
        files.append("nodes_wide.log")

        pods = _run(["kubectl", "--context", args.cluster_context, "-n", args.namespace, "get", "pods", "-o", "wide"])
        if pods.returncode != 0:
            raise RuntimeError((pods.stderr or pods.stdout).strip() or "kubectl get pods failed")
        _write_text(bundle_dir / "pods.log", redact_text(pods.stdout))
        files.append("pods.log")

        events = _run(
            [
                "kubectl",
                "--context",
                args.cluster_context,
                "-n",
                args.namespace,
                "get",
                "events",
                "--sort-by=.lastTimestamp",
            ]
        )
        if events.returncode != 0:
            raise RuntimeError((events.stderr or events.stdout).strip() or "kubectl get events failed")
        _write_text(bundle_dir / "events.log", redact_text(events.stdout))
        files.append("events.log")

    finished_at = args.finished_at or _utc_iso()
    receipt = {
        "schema_version": 1,
        "run_id": run_id,
        "mode": mode,
        "status": "executed" if args.execute else "planned",
        "passed": passed if args.execute else False,
        "cluster_context": args.cluster_context,
        "namespace": args.namespace,
        "started_at": started_at,
        "finished_at": finished_at,
        "captured_at": captured_at,
        "evidence_files": sorted(files),
    }
    _write_json(bundle_dir / "receipt.json", receipt)
    files.append("receipt.json")
    _write_manifest(bundle_dir, run_id=run_id, evidence_files=files)

    print(f"eks_connectivity_mode={mode}")
    print(f"eks_connectivity_run_id={run_id}")
    print(f"eks_connectivity_bundle={bundle_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
