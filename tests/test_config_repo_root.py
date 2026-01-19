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
