from __future__ import annotations

import importlib

import pytest


def test_candidate_state_contract_layout(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBINTEL_STATE_DIR", str(tmp_path / "state"))
    import ji_engine.config as config

    config = importlib.reload(config)
    paths = config.candidate_state_paths("alice")

    assert paths.root == config.STATE_DIR / "candidates" / "alice"
    assert paths.user_inputs == paths.root / "inputs"
    assert paths.system_state == paths.root / "system_state"
    assert paths.runs == paths.root / "runs"
    assert paths.history == paths.root / "history"
    assert paths.user_state == paths.root / "user_state"
    assert paths.profile_path == paths.user_inputs / "candidate_profile.json"
    assert paths.last_run_pointer_path == paths.system_state / "last_run.json"
    assert paths.last_success_pointer_path == paths.system_state / "last_success.json"
    assert paths.run_index_path == paths.system_state / "run_index.sqlite"


def test_candidate_pointer_read_paths_local_include_legacy(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBINTEL_STATE_DIR", str(tmp_path / "state"))
    import ji_engine.config as config

    config = importlib.reload(config)
    last_run_paths = config.candidate_last_run_read_paths("local")
    last_success_paths = config.candidate_last_success_read_paths("local")

    assert last_run_paths[0] == config.candidate_last_run_pointer_path("local")
    assert last_success_paths[0] == config.candidate_last_success_pointer_path("local")
    assert config.STATE_DIR / "last_run.json" in last_run_paths
    assert config.STATE_DIR / "last_success.json" in last_success_paths


def test_candidate_pointer_read_paths_non_local_no_global_fallback(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBINTEL_STATE_DIR", str(tmp_path / "state"))
    import ji_engine.config as config

    config = importlib.reload(config)
    last_run_paths = config.candidate_last_run_read_paths("alice")
    last_success_paths = config.candidate_last_success_read_paths("alice")

    assert config.STATE_DIR / "last_run.json" not in last_run_paths
    assert config.STATE_DIR / "last_success.json" not in last_success_paths


def test_candidate_state_contract_fail_closed():
    import ji_engine.config as config

    with pytest.raises(ValueError):
        config.candidate_state_paths("../escape")


def test_no_cross_candidate_path_bleed(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBINTEL_STATE_DIR", str(tmp_path / "state"))
    import ji_engine.config as config

    config = importlib.reload(config)
    alice = config.candidate_state_paths("alice")
    bob = config.candidate_state_paths("bob")

    assert alice.profile_path != bob.profile_path
    assert alice.last_success_pointer_path != bob.last_success_pointer_path
    assert alice.run_index_path != bob.run_index_path
