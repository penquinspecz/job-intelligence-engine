from __future__ import annotations

import json
import subprocess

from scripts import tofu_eks_vars_from_aws


class _Result:
    def __init__(self, stdout: str, returncode: int = 0):
        self.stdout = stdout
        self.stderr = ""
        self.returncode = returncode


def test_generates_deterministic_auto_tfvars(monkeypatch, tmp_path, capsys):
    out_file = tmp_path / "local.auto.tfvars.json"
    monkeypatch.setattr(tofu_eks_vars_from_aws, "OUT_FILE", out_file)

    monkeypatch.setenv("AWS_PROFILE", "jobintel-deployer")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("CLUSTER_NAME", "jobintel-eks")
    monkeypatch.setenv("JOBINTEL_ARTIFACTS_BUCKET", "jobintel-artifacts-prod")

    cluster_payload = {
        "cluster": {
            "resourcesVpcConfig": {
                "subnetIds": ["subnet-bbb", "subnet-aaa"],
                "vpcId": "vpc-1234",
            }
        }
    }

    def _fake_run(cmd, check=False, capture_output=False, text=False):
        assert check is False
        assert capture_output is True
        assert text is True
        assert cmd[:3] == ["aws", "eks", "describe-cluster"]
        return _Result(json.dumps(cluster_payload))

    monkeypatch.setattr(subprocess, "run", _fake_run)

    exit_code = tofu_eks_vars_from_aws.main()
    assert exit_code == 0

    payload = json.loads(out_file.read_text(encoding="utf-8"))
    assert payload == {
        "s3_bucket": "jobintel-artifacts-prod",
        "subnet_ids": ["subnet-aaa", "subnet-bbb"],
        "vpc_id": "vpc-1234",
    }

    output = capsys.readouterr().out
    assert str(out_file) in output
    assert "subnet_count=2" in output


def test_uses_cluster_default_bucket_when_bucket_env_missing(monkeypatch, tmp_path):
    out_file = tmp_path / "local.auto.tfvars.json"
    monkeypatch.setattr(tofu_eks_vars_from_aws, "OUT_FILE", out_file)

    monkeypatch.setenv("AWS_PROFILE", "jobintel-deployer")
    monkeypatch.delenv("AWS_REGION", raising=False)
    monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)
    monkeypatch.setenv("CLUSTER_NAME", "my-eks")
    monkeypatch.delenv("JOBINTEL_ARTIFACTS_BUCKET", raising=False)
    monkeypatch.delenv("JOBINTEL_S3_BUCKET", raising=False)

    cluster_payload = {
        "cluster": {
            "resourcesVpcConfig": {
                "subnetIds": ["subnet-z"],
                "vpcId": "vpc-9876",
            }
        }
    }

    def _fake_run(cmd, check=False, capture_output=False, text=False):
        assert "us-east-1" in cmd
        return _Result(json.dumps(cluster_payload))

    monkeypatch.setattr(subprocess, "run", _fake_run)

    exit_code = tofu_eks_vars_from_aws.main()
    assert exit_code == 0

    payload = json.loads(out_file.read_text(encoding="utf-8"))
    assert payload["s3_bucket"] == "my-eks-artifacts"
    assert payload["subnet_ids"] == ["subnet-z"]


def test_fails_without_aws_profile(monkeypatch):
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    exit_code = tofu_eks_vars_from_aws.main()
    assert exit_code == 2


def test_cli_cluster_name_overrides_env(monkeypatch, tmp_path):
    out_file = tmp_path / "local.auto.tfvars.json"
    monkeypatch.setattr(tofu_eks_vars_from_aws, "OUT_FILE", out_file)
    monkeypatch.setenv("AWS_PROFILE", "jobintel-deployer")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("CLUSTER_NAME", "env-cluster")

    seen_cmd: list[str] = []

    def _fake_run(cmd, check=False, capture_output=False, text=False):
        nonlocal seen_cmd
        seen_cmd = cmd
        return _Result('{"cluster":{"resourcesVpcConfig":{"subnetIds":["subnet-a"],"vpcId":"vpc-1"}}}')

    monkeypatch.setattr(subprocess, "run", _fake_run)

    exit_code = tofu_eks_vars_from_aws.main(["--cluster-name", "arg-cluster"])
    assert exit_code == 0
    assert "--name" in seen_cmd
    assert "arg-cluster" in seen_cmd
