from __future__ import annotations

import json
import sys
from pathlib import Path

import scripts.ops.eks_infra_plan_bundle as eks_infra_plan_bundle


class _Result:
    def __init__(self, stdout: str = "", stderr: str = "", returncode: int = 0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


def test_plan_bundle_deterministic_and_kubectl_free(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(eks_infra_plan_bundle, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(eks_infra_plan_bundle.shutil, "which", lambda name: "/usr/bin/tofu" if name == "tofu" else None)

    monkeypatch.setenv("AWS_PROFILE", "jobintel-deployer")
    monkeypatch.setenv("AWS_REGION", "us-east-1")

    calls: list[list[str]] = []

    def fake_run(cmd, *, env, cwd=None):  # type: ignore[no-untyped-def]
        calls.append(list(cmd))
        if cmd[:3] == ["aws", "sts", "get-caller-identity"]:
            return _Result('{"Arn":"arn:aws:iam::123456789012:role/jobintel-deployer"}')
        if cmd[:3] == ["aws", "eks", "describe-cluster"]:
            payload = {
                "cluster": {
                    "name": "jobintel-eks",
                    "resourcesVpcConfig": {
                        "subnetIds": ["subnet-b", "subnet-a"],
                        "vpcId": "vpc-123",
                    },
                }
            }
            return _Result(json.dumps(payload))
        if cmd[:2] == [sys.executable, "scripts/tofu_eks_vars_from_aws.py"]:
            out_file = tmp_path / "ops" / "aws" / "infra" / "eks" / "local.auto.tfvars.json"
            out_file.parent.mkdir(parents=True, exist_ok=True)
            out_file.write_text(
                json.dumps({"s3_bucket": "jobintel-eks-artifacts", "subnet_ids": ["subnet-a", "subnet-b"]}) + "\n",
                encoding="utf-8",
            )
            return _Result("ok\n")
        if cmd[-2:] == ["state", "list"]:
            return _Result("aws_eks_cluster.this\naws_eks_node_group.default\n")
        if cmd[-1] == "version":
            return _Result("OpenTofu v1.11.4\n")
        if cmd[-1] == "providers":
            return _Result("Providers required by configuration:\n")
        if cmd[-2:] == ["workspace", "show"]:
            return _Result("default\n")
        if cmd[-2:] == ["fmt", "-check"]:
            return _Result("")
        if cmd[-1] == "validate":
            return _Result("Success! The configuration is valid.\n")
        if "plan" in cmd:
            out_arg = next(part for part in cmd if part.startswith("-out="))
            plan_path = Path(out_arg.split("=", 1)[1])
            plan_path.parent.mkdir(parents=True, exist_ok=True)
            plan_path.write_bytes(b"fake-plan")
            return _Result("Plan: 0 to add, 0 to change, 0 to destroy.\n")
        if "show" in cmd:
            return _Result("No changes. Your infrastructure matches the configuration.\n")
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(eks_infra_plan_bundle, "_run", fake_run)

    args = [
        "--run-id",
        "unit-fixed",
        "--output-dir",
        "ops/proof/bundles",
        "--captured-at",
        "2026-02-10T12:00:00Z",
    ]

    rc_first = eks_infra_plan_bundle.main(args)
    rc_second = eks_infra_plan_bundle.main(args)

    assert rc_first == 0
    assert rc_second == 0
    assert not any(cmd and cmd[0] == "kubectl" for cmd in calls)

    bundle = tmp_path / "ops" / "proof" / "bundles" / "m4-unit-fixed" / "eks_infra"
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    receipt = json.loads((bundle / "receipt.json").read_text(encoding="utf-8"))

    assert receipt["mode"] == "plan"
    assert receipt["cluster_exists"] is True
    assert receipt["state_empty"] is False
    assert receipt["has_cluster_in_state"] is True

    names = [item["path"] for item in manifest["files"]]
    assert names == sorted(names)
    assert "tofu_plan_sanitized.txt" in names
    for item in manifest["files"]:
        assert len(item["sha256"]) == 64
        assert item["size_bytes"] > 0


def test_plan_bundle_fails_fast_when_cluster_exists_and_state_empty(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(eks_infra_plan_bundle, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(eks_infra_plan_bundle.shutil, "which", lambda name: "/usr/bin/tofu" if name == "tofu" else None)

    monkeypatch.setenv("AWS_PROFILE", "jobintel-deployer")
    monkeypatch.setenv("AWS_REGION", "us-east-1")

    plan_calls = 0

    def fake_run(cmd, *, env, cwd=None):  # type: ignore[no-untyped-def]
        nonlocal plan_calls
        if cmd[:3] == ["aws", "sts", "get-caller-identity"]:
            return _Result('{"Arn":"arn:aws:iam::123456789012:role/jobintel-deployer"}')
        if cmd[:3] == ["aws", "eks", "describe-cluster"]:
            return _Result(
                '{"cluster":{"name":"jobintel-eks","resourcesVpcConfig":{"subnetIds":["subnet-a"],"vpcId":"vpc-123"}}}'
            )
        if cmd[:2] == [sys.executable, "scripts/tofu_eks_vars_from_aws.py"]:
            return _Result("ok\n")
        if cmd[-2:] == ["state", "list"]:
            return _Result("", "No state file was found", 1)
        if "plan" in cmd:
            plan_calls += 1
            return _Result("", "should not run", 1)
        if (
            cmd[-1] in {"version", "providers", "validate"}
            or cmd[-2:] == ["workspace", "show"]
            or cmd[-2:] == ["fmt", "-check"]
        ):
            return _Result("ok\n")
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(eks_infra_plan_bundle, "_run", fake_run)

    rc = eks_infra_plan_bundle.main(["--run-id", "unit-empty", "--captured-at", "2026-02-10T12:00:00Z"])
    assert rc == 2
    assert plan_calls == 0

    receipt = json.loads(
        (tmp_path / "ops" / "proof" / "bundles" / "m4-unit-empty" / "eks_infra" / "receipt.json").read_text(
            encoding="utf-8"
        )
    )
    assert receipt["status"] == "failed"
    assert "state is empty while EKS cluster exists" in receipt["error"]
