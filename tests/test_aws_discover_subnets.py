from __future__ import annotations

import json
import subprocess

from scripts import aws_discover_subnets


class _Result:
    def __init__(self, stdout: str, returncode: int = 0):
        self.stdout = stdout
        self.stderr = ""
        self.returncode = returncode


def test_discover_subnets_deterministic(monkeypatch, capsys):
    vpcs = {
        "Vpcs": [
            {
                "VpcId": "vpc-2",
                "CidrBlock": "10.1.0.0/16",
                "IsDefault": False,
                "Tags": [{"Key": "Name", "Value": "jobintel-main"}],
            },
            {
                "VpcId": "vpc-1",
                "CidrBlock": "172.31.0.0/16",
                "IsDefault": True,
                "Tags": [{"Key": "Name", "Value": "default"}],
            },
        ]
    }
    subnets = {
        "Subnets": [
            {
                "SubnetId": "subnet-b",
                "VpcId": "vpc-2",
                "AvailabilityZone": "us-east-1b",
                "CidrBlock": "10.1.2.0/24",
                "MapPublicIpOnLaunch": False,
                "Tags": [{"Key": "Name", "Value": "jobintel-b"}],
            },
            {
                "SubnetId": "subnet-a",
                "VpcId": "vpc-2",
                "AvailabilityZone": "us-east-1a",
                "CidrBlock": "10.1.1.0/24",
                "MapPublicIpOnLaunch": False,
                "Tags": [{"Key": "Name", "Value": "jobintel-a"}],
            },
            {
                "SubnetId": "subnet-z",
                "VpcId": "vpc-1",
                "AvailabilityZone": "us-east-1c",
                "CidrBlock": "172.31.1.0/24",
                "MapPublicIpOnLaunch": True,
                "Tags": [{"Key": "Name", "Value": "default-z"}],
            },
        ]
    }

    def _fake_run(cmd, check=False, capture_output=False, text=False):
        if cmd[:3] == ["aws", "ec2", "describe-vpcs"]:
            return _Result(json.dumps(vpcs))
        if cmd[:3] == ["aws", "ec2", "describe-subnets"]:
            return _Result(json.dumps(subnets))
        if cmd[:3] == ["aws", "configure", "get"]:
            return _Result("us-east-1")
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(subprocess, "run", _fake_run)

    exit_code = aws_discover_subnets.main()
    assert exit_code == 0

    output = capsys.readouterr().out.strip().splitlines()
    json_payload = json.loads(output[-1])
    assert json_payload["region"] == "us-east-1"
    assert json_payload["preferred_vpc_ids"] == ["vpc-2"]
    assert json_payload["selected_subnet_ids"] == ["subnet-a", "subnet-b"]
    assert 'terraform apply -var \'subnet_ids=["subnet-a","subnet-b"]\'' in json_payload["terraform_snippet"]
