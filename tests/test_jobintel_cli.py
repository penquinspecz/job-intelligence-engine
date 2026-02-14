import types

import pytest

from jobintel import cli


def test_cli_run_forwards_flags(monkeypatch):
    captured = {}

    def fake_run(cmd, env=None, check=False, text=False, capture_output=False):
        captured["cmd"] = cmd
        captured["env"] = env
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(cli.subprocess, "run", fake_run)
    monkeypatch.setattr(cli, "_validate_candidate_for_run", lambda _: "local")

    rc = cli.main(
        [
            "run",
            "--offline",
            "--role",
            "cs",
            "--providers",
            "openai",
            "--no_post",
            "--no_enrich",
        ]
    )

    assert rc == 0
    cmd = captured["cmd"]
    assert "--profiles" in cmd
    assert "cs" in cmd
    assert "--providers" in cmd
    assert "openai" in cmd
    assert "--offline" in cmd
    assert "--no_post" in cmd
    assert "--no_enrich" in cmd


def test_cli_run_accepts_hyphen_aliases(monkeypatch):
    captured = {}

    def fake_run(cmd, env=None, check=False, text=False, capture_output=False):
        captured["cmd"] = cmd
        captured["env"] = env
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(cli.subprocess, "run", fake_run)
    monkeypatch.setattr(cli, "_validate_candidate_for_run", lambda _: "local")

    rc = cli.main(
        [
            "run",
            "--offline",
            "--role",
            "cs",
            "--providers",
            "openai",
            "--no-post",
            "--no-enrich",
        ]
    )

    assert rc == 0
    cmd = captured["cmd"]
    assert "--no_post" in cmd
    assert "--no_enrich" in cmd


def test_cli_run_daily_sets_candidate_id_env(monkeypatch):
    captured = {}

    def fake_run(cmd, env=None, check=False, text=False, capture_output=False):
        captured["cmd"] = cmd
        captured["env"] = env
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(cli.subprocess, "run", fake_run)
    monkeypatch.setattr(cli, "_validate_candidate_for_run", lambda _: "alice")

    rc = cli.main(["run", "daily", "--profiles", "cs", "--candidate-id", "alice"])

    assert rc == 0
    assert captured["env"]["JOBINTEL_CANDIDATE_ID"] == "alice"
    assert "--profiles" in captured["cmd"]
    assert "cs" in captured["cmd"]


def test_cli_run_daily_candidate_validation_failure(monkeypatch):
    monkeypatch.setattr(
        cli, "_validate_candidate_for_run", lambda _: (_ for _ in ()).throw(SystemExit("bad candidate"))
    )
    with pytest.raises(SystemExit, match="bad candidate"):
        cli.main(["run", "daily", "--profiles", "cs", "--candidate-id", "BAD"])


def test_cli_run_daily_prints_run_summary_path_when_present(tmp_path, monkeypatch, capsys):
    state_dir = tmp_path / "state"
    run_id = "2026-02-14T16:55:01Z"
    run_summary_path = state_dir / "runs" / "20260214T165501Z" / "run_summary.v1.json"
    run_summary_path.parent.mkdir(parents=True, exist_ok=True)
    run_summary_path.write_text(
        '{"status":"success","run_summary_schema_version":1}',
        encoding="utf-8",
    )

    monkeypatch.setattr(cli, "_validate_candidate_for_run", lambda _: "local")
    monkeypatch.setattr(cli, "RUN_METADATA_DIR", state_dir / "runs")
    monkeypatch.setattr(cli, "candidate_run_metadata_dir", lambda _: state_dir / "candidates" / "local" / "runs")

    def fake_run(cmd, env=None, check=False, text=False, capture_output=False):
        return types.SimpleNamespace(returncode=0, stdout=f"JOBINTEL_RUN_ID={run_id}\n", stderr="")

    monkeypatch.setattr(cli.subprocess, "run", fake_run)

    rc = cli.main(["run", "daily", "--profiles", "cs", "--candidate-id", "local"])
    assert rc == 0
    out = capsys.readouterr().out
    assert f"RUN_SUMMARY_PATH={run_summary_path}" in out


def test_cli_runs_list_prints_stable_table(monkeypatch, capsys):
    monkeypatch.setattr(
        cli,
        "list_runs_as_dicts",
        lambda candidate_id, limit: [
            {
                "run_id": "2026-02-14T16:55:02Z",
                "candidate_id": "local",
                "status": "success",
                "created_at": "2026-02-14T16:55:02Z",
                "summary_path": "state/runs/20260214T165502Z/run_summary.v1.json",
                "health_path": "state/runs/20260214T165502Z/run_health.v1.json",
                "git_sha": "abc123",
            },
            {
                "run_id": "2026-02-14T16:55:01Z",
                "candidate_id": "local",
                "status": "failed",
                "created_at": "2026-02-14T16:55:01Z",
                "summary_path": "state/runs/20260214T165501Z/run_summary.v1.json",
                "health_path": "state/runs/20260214T165501Z/run_health.v1.json",
                "git_sha": "def456",
            },
        ],
    )
    rc = cli.main(["runs", "list", "--candidate-id", "local", "--limit", "2"])
    assert rc == 0
    out = capsys.readouterr().out
    lines = [line for line in out.splitlines() if line]
    assert lines[0].startswith("RUN_ID")
    assert "CANDIDATE" in lines[0]
    assert "SUMMARY_PATH" in lines[0]
    assert "HEALTH_PATH" in lines[0]
    assert "GIT_SHA" in lines[0]
    assert lines[2].startswith("2026-02-14T16:55:02Z")
    assert lines[3].startswith("2026-02-14T16:55:01Z")
    assert lines[-1] == "ROWS=2"
