from __future__ import annotations

import subprocess
from pathlib import Path

from scripts import doctor


def _cp(returncode: int = 0, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=["cmd"], returncode=returncode, stdout=stdout, stderr=stderr)


def test_parse_worktrees_marks_detached() -> None:
    raw = """worktree /repo
HEAD deadbeef
detached

"""
    parsed = doctor._parse_worktrees(raw)
    assert parsed[0]["detached"] == "true"


def test_check_worktrees_fails_when_main_in_multiple_worktrees(monkeypatch, tmp_path: Path) -> None:
    repo = tmp_path
    raw = f"""worktree {repo}
HEAD aaa
branch refs/heads/main

worktree /tmp/other
HEAD bbb
branch refs/heads/main

"""
    monkeypatch.setattr(doctor, "_run", lambda cmd, root: _cp(stdout=raw))
    result = doctor._check_worktrees(repo)
    assert result.ok is False
    assert "multiple worktrees" in result.detail


def test_check_worktrees_fails_when_current_detached(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    repo = tmp_path
    raw = f"""worktree {repo}
HEAD deadbeef
detached

"""
    monkeypatch.setattr(doctor, "_run", lambda cmd, root: _cp(stdout=raw))
    result = doctor._check_worktrees(repo)
    assert result.ok is False
    assert "detached" in result.detail


def test_check_docs_includes_run_report(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir(parents=True)
    (tmp_path / "config").mkdir(parents=True)
    (tmp_path / "schemas").mkdir(parents=True)
    (tmp_path / "docs" / "DETERMINISM_CONTRACT.md").write_text("ok", encoding="utf-8")
    (tmp_path / "config" / "scoring.v1.json").write_text("{}", encoding="utf-8")
    (tmp_path / "schemas" / "run_health.schema.v1.json").write_text("{}", encoding="utf-8")

    result = doctor._check_docs(tmp_path)
    assert result.ok is False
    assert "docs/RUN_REPORT.md" in result.detail


def test_check_pytest_harness_validates_defaults_and_marker(monkeypatch, tmp_path: Path) -> None:
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir(parents=True)
    (tests_dir / "conftest.py").write_text(
        "\n".join(
            [
                "AWS_EC2_METADATA_DISABLED = 'true'",
                "AWS_CONFIG_FILE = '/dev/null'",
                "AWS_SHARED_CREDENTIALS_FILE = '/dev/null'",
                "# aws_integration",
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / "pytest.ini").write_text("[pytest]\nmarkers =\n  aws_integration: x\n", encoding="utf-8")
    monkeypatch.setattr(
        doctor,
        "_run",
        lambda cmd, root: _cp(stdout="aws_integration: requires live AWS credentials/network access"),
    )
    result = doctor._check_pytest_harness(tmp_path)
    assert result.ok is True


def test_check_state_dir_warns_inside_repo(monkeypatch, tmp_path: Path) -> None:
    inside = tmp_path / "state"
    inside.mkdir(parents=True)
    monkeypatch.setenv("JOBINTEL_STATE_DIR", str(inside))
    result = doctor._check_state_dir_invariant(tmp_path)
    assert result.ok is True
    assert "WARNING" in result.detail
