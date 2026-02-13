from __future__ import annotations

import importlib
import json
from pathlib import Path


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _reload_modules():
    import ji_engine.candidates.registry as candidate_registry
    import ji_engine.config as config
    import scripts.candidates as candidates_cli

    importlib.reload(config)
    importlib.reload(candidate_registry)
    candidates_cli = importlib.reload(candidates_cli)
    return config, candidate_registry, candidates_cli


def test_candidate_add_creates_namespaced_dirs(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("JOBINTEL_STATE_DIR", str(tmp_path / "state"))
    config, _candidate_registry, candidates_cli = _reload_modules()

    rc = candidates_cli.main(["add", "alice", "--display-name", "Alice Example", "--json"])
    assert rc == 0
    created = json.loads(capsys.readouterr().out)

    assert created["candidate_id"] == "alice"
    assert created["registry_path"] == str(config.STATE_DIR / "candidates" / "registry.json")
    assert config.candidate_state_dir("alice").exists()
    assert config.candidate_run_metadata_dir("alice").exists()
    assert config.candidate_history_dir("alice").exists()
    assert config.candidate_user_state_dir("alice").exists()

    profile = _read(config.candidate_profile_path("alice"))
    assert profile["candidate_id"] == "alice"
    assert profile["display_name"] == "Alice Example"


def test_candidate_add_honors_state_dir_override(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("JOBINTEL_STATE_DIR", str(tmp_path / "state_default"))
    _config, _candidate_registry, candidates_cli = _reload_modules()

    override_state = tmp_path / "state_override"
    rc = candidates_cli.main(
        [
            "--state-dir",
            str(override_state),
            "add",
            "alice",
            "--json",
        ]
    )
    assert rc == 0
    created = json.loads(capsys.readouterr().out)
    assert created["registry_path"] == str(override_state / "candidates" / "registry.json")
    assert Path(created["profile_path"]).is_file()
    assert Path(created["candidate_dir"]) == override_state / "candidates" / "alice"
    assert not (tmp_path / "state_default" / "candidates" / "alice").exists()


def test_candidate_add_rejects_invalid_candidate_id(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("JOBINTEL_STATE_DIR", str(tmp_path / "state"))
    _config, _candidate_registry, candidates_cli = _reload_modules()

    rc = candidates_cli.main(["add", "BAD-ID"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "candidate_id must be lowercase" in err or "candidate_id must match" in err


def test_candidate_profile_validation(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("JOBINTEL_STATE_DIR", str(tmp_path / "state"))
    config, _candidate_registry, candidates_cli = _reload_modules()

    rc = candidates_cli.main(["add", "bob"])
    assert rc == 0
    capsys.readouterr()

    profile_path = config.candidate_profile_path("bob")
    broken = _read(profile_path)
    broken.pop("display_name")
    profile_path.write_text(json.dumps(broken), encoding="utf-8")

    rc = candidates_cli.main(["validate", "--json"])
    assert rc == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert any("invalid candidate profile" in item for item in payload["errors"])


def test_ingest_text_writes_hashed_artifact(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("JOBINTEL_STATE_DIR", str(tmp_path / "state"))
    config, _candidate_registry, candidates_cli = _reload_modules()

    assert candidates_cli.main(["add", "alice"]) == 0
    capsys.readouterr()
    rc = candidates_cli.main(
        [
            "ingest-text",
            "alice",
            "--resume-text",
            "Experienced CS leader with enterprise GTM background.",
            "--json",
        ]
    )
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    artifact = payload["text_input_artifacts"]["resume_text"]
    assert len(artifact["sha256"]) == 64
    artifact_path = config.STATE_DIR / artifact["artifact_path"]
    assert artifact_path.exists()
    artifact_payload = _read(artifact_path)
    assert artifact_payload["text"] == "Experienced CS leader with enterprise GTM background."


def test_ingest_text_enforces_max_size(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("JOBINTEL_STATE_DIR", str(tmp_path / "state"))
    _config, _candidate_registry, candidates_cli = _reload_modules()

    assert candidates_cli.main(["add", "alice"]) == 0
    capsys.readouterr()
    huge = "a" * 120001
    rc = candidates_cli.main(["ingest-text", "alice", "--resume-text", huge])
    assert rc == 2
    assert "exceeds max bytes" in capsys.readouterr().err


def test_ingest_text_output_does_not_leak_raw_text(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("JOBINTEL_STATE_DIR", str(tmp_path / "state"))
    _config, _candidate_registry, candidates_cli = _reload_modules()

    secret_like = "Authorization: Bearer token_abcdefghijklmnopqrstuvwxyz12345"
    assert candidates_cli.main(["add", "alice"]) == 0
    capsys.readouterr()
    rc = candidates_cli.main(["ingest-text", "alice", "--resume-text", secret_like])
    assert rc == 0
    out = capsys.readouterr().out
    assert "updated candidate text" in out
    assert secret_like not in out


def test_set_profile_text_alias(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("JOBINTEL_STATE_DIR", str(tmp_path / "state"))
    _config, _candidate_registry, candidates_cli = _reload_modules()

    assert candidates_cli.main(["add", "alice"]) == 0
    capsys.readouterr()
    rc = candidates_cli.main(["set-profile-text", "alice", "--summary-text", "Hands-on operator", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["updated_fields"] == ["summary_text"]


def test_bootstrap_creates_template_and_next_steps(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("JOBINTEL_STATE_DIR", str(tmp_path / "state"))
    config, _candidate_registry, candidates_cli = _reload_modules()

    rc = candidates_cli.main(["bootstrap", "alice"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "bootstrapped candidate candidate_id=alice" in out
    assert "next_steps:" in out
    assert "run daily --candidate-id alice" in out

    profile = _read(config.candidate_profile_path("alice"))
    assert profile["target_roles"] == ["replace_with_target_role"]
    assert profile["preferred_locations"] == ["replace_with_location"]
    assert (config.candidate_state_dir("alice") / "system_state").exists()
    assert (config.candidate_state_dir("alice") / "inputs").exists()


def test_doctor_validates_pointer_and_no_raw_text_leak(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("JOBINTEL_STATE_DIR", str(tmp_path / "state"))
    _config, _candidate_registry, candidates_cli = _reload_modules()

    secret_like = "Authorization: Bearer super-secret-123"
    assert candidates_cli.main(["bootstrap", "alice"]) == 0
    capsys.readouterr()
    assert candidates_cli.main(["ingest-text", "alice", "--resume-text", secret_like]) == 0
    capsys.readouterr()

    rc = candidates_cli.main(["doctor", "alice"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "candidate doctor: OK candidate_id=alice" in out
    assert secret_like not in out


def test_doctor_fails_when_pointer_missing(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("JOBINTEL_STATE_DIR", str(tmp_path / "state"))
    config, _candidate_registry, candidates_cli = _reload_modules()

    assert candidates_cli.main(["bootstrap", "alice"]) == 0
    capsys.readouterr()
    assert candidates_cli.main(["ingest-text", "alice", "--summary-text", "hello", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    pointer = payload["text_input_artifacts"]["summary_text"]["artifact_path"]
    (config.STATE_DIR / pointer).unlink()

    rc = candidates_cli.main(["doctor", "alice", "--json"])
    assert rc == 2
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False
    assert any("missing file" in err for err in out["errors"])
