import json
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
        json.dumps(
            {
                "status": "success",
                "run_summary_schema_version": 1,
                "primary_artifacts": [
                    {"path": "state/runs/20260214T165501Z/openai/cs/openai_ranked_jobs.cs.json"},
                    {"path": "state/runs/20260214T165501Z/openai/cs/openai_ranked_jobs.cs.csv"},
                    {"path": "state/runs/20260214T165501Z/openai/cs/openai_shortlist.cs.md"},
                ],
            }
        ),
        encoding="utf-8",
    )
    run_health_path = run_summary_path.parent / "run_health.v1.json"
    run_health_path.write_text('{"status":"success"}', encoding="utf-8")

    monkeypatch.setattr(cli, "_validate_candidate_for_run", lambda _: "local")
    monkeypatch.setattr(cli, "RUN_METADATA_DIR", state_dir / "runs")
    monkeypatch.setattr(cli, "candidate_run_metadata_dir", lambda _: state_dir / "candidates" / "local" / "runs")

    def fake_run(cmd, env=None, check=False, text=False, capture_output=False):
        return types.SimpleNamespace(returncode=0, stdout=f"JOBINTEL_RUN_ID={run_id}\n", stderr="")

    monkeypatch.setattr(cli.subprocess, "run", fake_run)

    rc = cli.main(["run", "daily", "--profiles", "cs", "--candidate-id", "local"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "RUN_RECEIPT_BEGIN" in out
    assert f"run_id={run_id}" in out
    assert f"run_dir={run_summary_path.parent}" in out
    assert f"run_summary={run_summary_path}" in out
    assert f"run_health={run_health_path}" in out
    assert "primary_artifact_1=" in out
    assert "primary_artifact_2=" in out
    assert "primary_artifact_3=" in out
    assert "RUN_RECEIPT_END" in out
    assert f"RUN_SUMMARY_PATH={run_summary_path}" in out


def test_cli_run_daily_run_receipt_on_partial_or_failed(tmp_path, monkeypatch, capsys):
    state_dir = tmp_path / "state"
    run_id = "2026-02-14T16:55:01Z"
    run_dir = state_dir / "runs" / "20260214T165501Z"
    run_summary_path = run_dir / "run_summary.v1.json"
    run_health_path = run_dir / "run_health.v1.json"
    run_dir.mkdir(parents=True, exist_ok=True)
    run_summary_path.write_text(
        json.dumps({"status": "failed", "run_summary_schema_version": 1, "primary_artifacts": []}),
        encoding="utf-8",
    )
    run_health_path.write_text('{"status":"failed"}', encoding="utf-8")

    monkeypatch.setattr(cli, "_validate_candidate_for_run", lambda _: "local")
    monkeypatch.setattr(cli, "RUN_METADATA_DIR", state_dir / "runs")
    monkeypatch.setattr(cli, "candidate_run_metadata_dir", lambda _: state_dir / "candidates" / "local" / "runs")

    def fake_run(cmd, env=None, check=False, text=False, capture_output=False):
        return types.SimpleNamespace(returncode=2, stdout=f"JOBINTEL_RUN_ID={run_id}\n", stderr="")

    monkeypatch.setattr(cli.subprocess, "run", fake_run)

    rc = cli.main(["run", "daily", "--profiles", "cs", "--candidate-id", "local"])
    assert rc == 2
    out = capsys.readouterr().out
    lines = [line for line in out.splitlines() if line]
    receipt_start = lines.index("RUN_RECEIPT_BEGIN")
    assert lines[receipt_start + 1] == f"run_id={run_id}"
    assert lines[receipt_start + 2] == f"run_dir={run_dir}"
    assert lines[receipt_start + 3] == "status=failed"
    assert lines[receipt_start + 4] == f"run_summary={run_summary_path}"
    assert lines[receipt_start + 5] == f"run_health={run_health_path}"
    assert lines[receipt_start + 6] == "RUN_RECEIPT_END"
    assert "RUN_SUMMARY_PATH=" not in out


def test_cli_run_daily_receipt_does_not_print_raw_text(tmp_path, monkeypatch, capsys):
    state_dir = tmp_path / "state"
    run_id = "2026-02-14T16:55:01Z"
    run_summary_path = state_dir / "runs" / "20260214T165501Z" / "run_summary.v1.json"
    run_summary_path.parent.mkdir(parents=True, exist_ok=True)
    run_summary_path.write_text(
        json.dumps(
            {
                "status": "success",
                "run_summary_schema_version": 1,
                "resume_text": "TOP_SECRET_RESUME_TEXT",
                "primary_artifacts": [],
            }
        ),
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
    assert "TOP_SECRET_RESUME_TEXT" not in out
