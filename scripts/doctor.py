#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
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
    unexpected_main_holders: List[str] = []
    for entry in _parse_worktrees(cp.stdout):
        branch = entry.get("branch", "")
        wt = entry.get("worktree", "")
        if not wt:
            continue
        if branch.endswith("/main") and str(Path(wt).resolve()) != cwd:
            unexpected_main_holders.append(wt)
    if unexpected_main_holders:
        return CheckResult(
            "worktrees",
            False,
            "unexpected worktree(s) holding main: " + ", ".join(sorted(unexpected_main_holders)),
        )
    return CheckResult("worktrees", True, "no unexpected worktrees holding main")


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
        "config/scoring.v1.json",
        "schemas/run_health.schema.v1.json",
    ]
    missing = [path for path in required if not (repo_root / path).exists()]
    if missing:
        return CheckResult("ci_parity_docs", False, "missing required contract files: " + ", ".join(missing))
    return CheckResult("ci_parity_docs", True, "determinism parity contract files present")


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
