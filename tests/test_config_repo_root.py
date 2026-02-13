import importlib
from pathlib import Path

import ji_engine.config as config_module


def test_repo_root_is_independent_of_cwd(tmp_path, monkeypatch):
    repo_root = Path(__file__).resolve().parents[1]
    monkeypatch.delenv("JOBINTEL_DATA_DIR", raising=False)
    monkeypatch.delenv("JOBINTEL_STATE_DIR", raising=False)
    monkeypatch.delenv("CI", raising=False)

    monkeypatch.chdir(tmp_path)
    config = importlib.reload(config_module)

    assert config.REPO_ROOT == repo_root
    assert config.DATA_DIR == repo_root / "data"
    assert config.STATE_DIR == repo_root / "state"
    assert config.SNAPSHOT_DIR == repo_root / "data" / "openai_snapshots"
    assert config.HISTORY_DIR == repo_root / "state" / "history"
    assert config.RUN_METADATA_DIR == repo_root / "state" / "runs"
    assert config.candidate_run_metadata_dir("local") == repo_root / "state" / "candidates" / "local" / "runs"
    assert (
        config.candidate_profile_path("local")
        == repo_root / "state" / "candidates" / "local" / "inputs" / "candidate_profile.json"
    )
    assert (
        config.candidate_last_success_pointer_path("local")
        == repo_root / "state" / "candidates" / "local" / "system_state" / "last_success.json"
    )


def test_candidate_id_sanitizer():
    config = importlib.reload(config_module)

    assert config.sanitize_candidate_id("local") == "local"
    assert config.sanitize_candidate_id("abc_123") == "abc_123"

    for bad in ("", "UPPER", "a-b", "../x", "x/y", "a" * 65):
        try:
            config.sanitize_candidate_id(bad)
            raise AssertionError(f"expected ValueError for {bad!r}")
        except ValueError:
            pass
