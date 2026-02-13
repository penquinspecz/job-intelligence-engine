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
    assert config.candidate_state_dir("alice").exists()
    assert config.candidate_run_metadata_dir("alice").exists()
    assert config.candidate_history_dir("alice").exists()
    assert config.candidate_user_state_dir("alice").exists()

    profile = _read(config.candidate_state_dir("alice") / "candidate_profile.json")
    assert profile["candidate_id"] == "alice"
    assert profile["display_name"] == "Alice Example"


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

    profile_path = config.candidate_state_dir("bob") / "candidate_profile.json"
    broken = _read(profile_path)
    broken.pop("display_name")
    profile_path.write_text(json.dumps(broken), encoding="utf-8")

    rc = candidates_cli.main(["validate", "--json"])
    assert rc == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert any("invalid candidate profile" in item for item in payload["errors"])
