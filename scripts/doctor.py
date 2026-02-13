#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Sequence


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    detail: str


def _run(cmd: Sequence[str], repo_root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(cmd),
        cwd=str(repo_root),
        text=True,
        capture_output=True,
        check=False,
    )


def _is_ci() -> bool:
    return os.environ.get("GITHUB_ACTIONS", "").lower() == "true"


def _parse_worktrees(raw: str) -> List[dict[str, str]]:
    entries: List[dict[str, str]] = []
    current: dict[str, str] = {}
    for line in raw.splitlines():
        if not line.strip():
            if current:
                entries.append(current)
                current = {}
            continue
        if " " not in line:
            if line.strip() == "detached":
                current["detached"] = "true"
            continue
        key, value = line.split(" ", 1)
        current[key] = value.strip()
    if current:
        entries.append(current)
    return entries


def _check_git_clean(repo_root: Path) -> CheckResult:
    cp = _run(("git", "status", "--porcelain=v1"), repo_root)
    if cp.returncode != 0:
        return CheckResult("git_clean", False, cp.stderr.strip() or "git status failed")
    if cp.stdout.strip():
        return CheckResult("git_clean", False, "worktree is dirty; commit/stash before CI-sensitive operations")
    return CheckResult("git_clean", True, "git status is clean")


def _check_worktrees(repo_root: Path) -> CheckResult:
    cp = _run(("git", "worktree", "list", "--porcelain"), repo_root)
    if cp.returncode != 0:
        return CheckResult("worktrees", False, cp.stderr.strip() or "git worktree list failed")
    cwd = str(repo_root.resolve())
    main_holders: List[str] = []
    current_detached = False
    for entry in _parse_worktrees(cp.stdout):
        branch = entry.get("branch", "")
        wt = entry.get("worktree", "")
        if not wt:
            continue
        wt_resolved = str(Path(wt).resolve())
        if branch.endswith("/main"):
            main_holders.append(wt_resolved)
        if wt_resolved == cwd and entry.get("detached") == "true":
            current_detached = True

    if current_detached:
        if _is_ci():
            return CheckResult("worktrees", True, "detached checkout allowed in CI job")
        return CheckResult("worktrees", False, "current worktree is detached; checkout a branch (expected: main)")
    if len(main_holders) > 1:
        return CheckResult(
            "worktrees",
            False,
            "main is checked out in multiple worktrees: " + ", ".join(sorted(main_holders)),
        )
    return CheckResult("worktrees", True, "worktree branch topology is sane")


def _check_venv(repo_root: Path) -> CheckResult:
    venv_python = repo_root / ".venv" / "bin" / "python"
    if not venv_python.exists():
        return CheckResult("venv", False, "missing .venv/bin/python")

    version_cp = _run((str(venv_python), "-c", "import sys; print(sys.version.split()[0])"), repo_root)
    if version_cp.returncode != 0:
        return CheckResult("venv", False, "unable to execute .venv/bin/python")
    got = version_cp.stdout.strip()

    pin_path = repo_root / ".python-version"
    if pin_path.exists():
        expected = pin_path.read_text(encoding="utf-8").strip()
        if expected and got != expected:
            return CheckResult(
                "venv",
                False,
                f".venv python version mismatch (expected {expected}, got {got})",
            )
    return CheckResult("venv", True, f".venv python version is {got}")


def _check_docs(repo_root: Path) -> CheckResult:
    required = [
        "docs/DETERMINISM_CONTRACT.md",
        "docs/RUN_REPORT.md",
        "config/scoring.v1.json",
        "schemas/run_health.schema.v1.json",
    ]
    missing = [path for path in required if not (repo_root / path).exists()]
    if missing:
        return CheckResult("ci_parity_docs", False, "missing required contract files: " + ", ".join(missing))
    return CheckResult("ci_parity_docs", True, "determinism parity contract files present")


def _check_pytest_harness(repo_root: Path) -> CheckResult:
    conftest_path = repo_root / "tests" / "conftest.py"
    pytest_ini_path = repo_root / "pytest.ini"
    if not conftest_path.exists():
        return CheckResult("pytest_harness", False, "missing tests/conftest.py")
    if not pytest_ini_path.exists():
        return CheckResult("pytest_harness", False, "missing pytest.ini")

    conftest = conftest_path.read_text(encoding="utf-8")
    pytest_ini = pytest_ini_path.read_text(encoding="utf-8")
    required_env_keys = (
        "AWS_EC2_METADATA_DISABLED",
        "AWS_CONFIG_FILE",
        "AWS_SHARED_CREDENTIALS_FILE",
    )
    missing_env_keys = [key for key in required_env_keys if key not in conftest]
    if missing_env_keys:
        return CheckResult(
            "pytest_harness",
            False,
            "offline AWS defaults missing in tests/conftest.py: " + ", ".join(missing_env_keys),
        )
    if "aws_integration" not in conftest and "aws_integration" not in pytest_ini:
        return CheckResult("pytest_harness", False, "aws_integration marker/opt-in wiring missing")

    venv_python = repo_root / ".venv" / "bin" / "python"
    python_bin = str(venv_python if venv_python.exists() else Path(sys.executable))
    marker_cp = _run((python_bin, "-m", "pytest", "--markers"), repo_root)
    if marker_cp.returncode != 0:
        if _is_ci() and "No module named pytest" in (marker_cp.stderr or ""):
            return CheckResult(
                "pytest_harness", True, "pytest marker runtime check skipped in CI (pytest not installed)"
            )
        return CheckResult(
            "pytest_harness",
            False,
            marker_cp.stderr.strip() or "pytest marker discovery failed",
        )
    if "aws_integration" not in marker_cp.stdout:
        return CheckResult("pytest_harness", False, "pytest marker discovery missing aws_integration")
    return CheckResult("pytest_harness", True, "offline harness defaults + marker discovery are valid")


def _check_state_dir_invariant(repo_root: Path) -> CheckResult:
    state_dir = os.getenv("JOBINTEL_STATE_DIR")
    if not state_dir:
        return CheckResult("state_dir", True, "JOBINTEL_STATE_DIR is not set")
    resolved_state = Path(state_dir).expanduser().resolve()
    resolved_repo = repo_root.resolve()
    if resolved_repo in (resolved_state, *resolved_state.parents):
        return CheckResult(
            "state_dir",
            True,
            f"JOBINTEL_STATE_DIR={resolved_state} (WARNING: points inside repo; prefer external path)",
        )
    return CheckResult("state_dir", True, f"JOBINTEL_STATE_DIR={resolved_state}")


def _check_k8s_overlay_render(repo_root: Path) -> CheckResult:
    venv_python = repo_root / ".venv" / "bin" / "python"
    python_bin = str(venv_python if venv_python.exists() else Path(sys.executable))
    cmd = (python_bin, "scripts/k8s_render.py", "--overlay", "onprem-pi", "--stdout", "--limit", "40")
    cp = _run(cmd, repo_root)
    if cp.returncode != 0:
        detail = cp.stderr.strip() or cp.stdout.strip() or "overlay render failed"
        if _is_ci() and "No module named 'yaml'" in detail:
            return CheckResult("k8s_overlay", True, "overlay render runtime check skipped in CI (PyYAML not installed)")
        return CheckResult(
            "k8s_overlay",
            False,
            f"unable to render onprem-pi overlay: {detail}. Ensure overlay files are valid and scripts/k8s_render.py supports local rendering without kubectl.",
        )
    line_count = len(cp.stdout.splitlines())
    if line_count == 0:
        return CheckResult("k8s_overlay", False, "overlay render produced no output")
    return CheckResult("k8s_overlay", True, f"onprem-pi overlay rendered ({line_count} line(s) sampled)")


def _line(result: CheckResult) -> str:
    level = "PASS" if result.ok else "FAIL"
    return f"[{level}] {result.name}: {result.detail}"


def main() -> int:
    parser = argparse.ArgumentParser(description="SignalCraft local guardrail doctor")
    parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    checks = [
        _check_git_clean(repo_root),
        _check_worktrees(repo_root),
        _check_venv(repo_root),
        _check_docs(repo_root),
        _check_pytest_harness(repo_root),
        _check_state_dir_invariant(repo_root),
        _check_k8s_overlay_render(repo_root),
    ]

    print("SignalCraft doctor")
    for check in checks:
        print(_line(check))

    failures = [c for c in checks if not c.ok]
    if failures:
        print(f"doctor: {len(failures)} failing check(s)")
        return 2
    print("doctor: all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
