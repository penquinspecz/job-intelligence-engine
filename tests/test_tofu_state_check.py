from __future__ import annotations

import os
import subprocess
from pathlib import Path
from textwrap import dedent


def _write_executable(path: Path, content: str) -> None:
    path.write_text(dedent(content).lstrip(), encoding="utf-8")
    path.chmod(0o755)


def _install_fake_tofu(bin_dir: Path) -> None:
    _write_executable(
        bin_dir / "tofu",
        """
        #!/usr/bin/env bash
        set -euo pipefail

        cmd=""
        subcmd=""
        nonopt=()
        for arg in "$@"; do
          if [[ "$arg" == -chdir=* ]]; then
            continue
          fi
          nonopt+=("$arg")
        done

        if [[ ${#nonopt[@]} -gt 0 ]]; then
          cmd="${nonopt[0]}"
        fi
        if [[ ${#nonopt[@]} -gt 1 ]]; then
          subcmd="${nonopt[1]}"
        fi

        case "$cmd" in
          workspace)
            if [[ "$subcmd" == "show" ]]; then
              echo "default"
              exit 0
            fi
            if [[ "$subcmd" == "list" ]]; then
              echo "* default"
              exit 0
            fi
            ;;
          state)
            if [[ "$subcmd" == "list" ]]; then
              if [[ "${FAKE_STATE_MODE:-nonempty}" == "empty" ]]; then
                echo "No state file was found!" >&2
                exit 1
              fi
              echo "aws_eks_cluster.this"
              echo "aws_eks_node_group.default"
              exit 0
            fi
            ;;
          import)
            if [[ -n "${TOFU_IMPORT_LOG:-}" ]]; then
              echo "$*" >> "${TOFU_IMPORT_LOG}"
            fi
            exit 0
            ;;
        esac

        exit 0
        """,
    )


def _install_fake_aws(bin_dir: Path) -> None:
    _write_executable(
        bin_dir / "aws",
        """
        #!/usr/bin/env bash
        set -euo pipefail

        if [[ "$1" == "eks" && "$2" == "describe-cluster" ]]; then
          if [[ "$*" == *"--query cluster.status"* ]]; then
            echo "ACTIVE"
            exit 0
          fi
          if [[ "$*" == *"--query cluster.identity.oidc.issuer"* ]]; then
            echo "https://oidc.eks.us-east-1.amazonaws.com/id/ABC"
            exit 0
          fi
          if [[ "$*" == *"--query cluster.resourcesVpcConfig.subnetIds[]"* ]]; then
            echo -e "subnet-b\tsubnet-a"
            exit 0
          fi
          cat <<'JSON'
{"cluster":{"name":"jobintel-eks","status":"ACTIVE","resourcesVpcConfig":{"subnetIds":["subnet-b","subnet-a"],"vpcId":"vpc-123"}}}
JSON
          exit 0
        fi

        if [[ "$1" == "iam" && "$2" == "list-open-id-connect-providers" ]]; then
          echo "arn:aws:iam::123456789012:oidc-provider/oidc.eks.us-east-1.amazonaws.com/id/ABC"
          exit 0
        fi

        if [[ "$1" == "iam" && "$2" == "get-open-id-connect-provider" ]]; then
          if [[ "$*" == *"--query Url"* ]]; then
            echo "oidc.eks.us-east-1.amazonaws.com/id/ABC"
          else
            echo "{}"
          fi
          exit 0
        fi

        if [[ "$1" == "iam" && "$2" == "list-policies" ]]; then
          echo "arn:aws:iam::123456789012:policy/jobintel-eks-jobintel-s3"
          exit 0
        fi

        echo "{}"
        exit 0
        """,
    )


def _prepare_fake_env(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    repo = tmp_path / "repo"
    (repo / "ops" / "aws" / "infra" / "eks").mkdir(parents=True, exist_ok=True)
    (repo / "ops" / "aws" / "infra" / "eks" / "main.tf").write_text("terraform {}\n", encoding="utf-8")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    _install_fake_tofu(bin_dir)
    _install_fake_aws(bin_dir)

    env = {
        "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
        "TOFU_STATE_CHECK_ROOT_DIR": str(repo),
        "AWS_PROFILE": "jobintel-deployer",
        "AWS_REGION": "us-east-1",
        "CLUSTER_NAME": "jobintel-eks",
        "RUN_ID": "unit-test",
    }
    return repo, env


def test_print_imports_stable_and_no_eval(tmp_path: Path) -> None:
    repo, env = _prepare_fake_env(tmp_path)
    env["FAKE_STATE_MODE"] = "empty"

    script = Path(__file__).resolve().parents[1] / "scripts" / "ops" / "tofu_state_check.sh"

    first = subprocess.run(["bash", str(script), "--print-imports"], capture_output=True, text=True, env=env)
    second = subprocess.run(["bash", str(script), "--print-imports"], capture_output=True, text=True, env=env)

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr

    import_script = repo / "ops" / "proof" / "bundles" / "m4-unit-test" / "eks_infra" / "import.sh"
    assert import_script.exists()

    contents_first = import_script.read_text(encoding="utf-8")
    contents_second = import_script.read_text(encoding="utf-8")
    assert contents_first == contents_second
    assert "eval " not in contents_first

    lines = [line for line in contents_first.splitlines() if " import aws_" in line]

    expected_order = [
        "import aws_iam_role.eks_cluster",
        "import aws_iam_role_policy_attachment.eks_cluster_policy",
        "import aws_iam_role_policy_attachment.eks_service_policy",
        "import aws_eks_cluster.this",
        "import aws_iam_role.node",
        "import aws_iam_role_policy_attachment.node_worker",
        "import aws_iam_role_policy_attachment.node_cni",
        "import aws_iam_role_policy_attachment.node_ecr",
        "import aws_eks_node_group.default",
        "import aws_iam_openid_connect_provider.this",
        "import aws_iam_role.jobintel_irsa",
        "import aws_iam_policy.jobintel_s3",
        "import aws_iam_role_policy_attachment.jobintel_s3",
    ]
    positions = {}
    for needle in expected_order:
        idx = next((i for i, line in enumerate(lines) if needle in line), None)
        assert idx is not None, needle
        positions[needle] = idx

    assert [positions[item] for item in expected_order] == sorted(positions.values())


def test_run_imports_requires_do_import_and_existing_script(tmp_path: Path) -> None:
    repo, env = _prepare_fake_env(tmp_path)
    env["FAKE_STATE_MODE"] = "empty"
    env["TOFU_IMPORT_LOG"] = str(tmp_path / "tofu_import.log")

    script = Path(__file__).resolve().parents[1] / "scripts" / "ops" / "tofu_state_check.sh"

    missing = subprocess.run(["bash", str(script), "--run-imports"], capture_output=True, text=True, env=env)
    assert missing.returncode != 0
    assert "import script not found" in (missing.stderr + missing.stdout)

    gen = subprocess.run(["bash", str(script), "--print-imports"], capture_output=True, text=True, env=env)
    assert gen.returncode == 0

    no_gate = subprocess.run(["bash", str(script), "--run-imports"], capture_output=True, text=True, env=env)
    assert no_gate.returncode != 0
    assert "DO_IMPORT must be 1" in (no_gate.stderr + no_gate.stdout)
    assert not Path(env["TOFU_IMPORT_LOG"]).exists()

    yes_gate_env = dict(env)
    yes_gate_env["DO_IMPORT"] = "1"
    run_ok = subprocess.run(["bash", str(script), "--run-imports"], capture_output=True, text=True, env=yes_gate_env)
    assert run_ok.returncode == 0

    import_log = Path(env["TOFU_IMPORT_LOG"]).read_text(encoding="utf-8")
    assert "import aws_eks_cluster.this" in import_log
    assert "import aws_eks_node_group.default" in import_log
