import os
from pathlib import Path

import ji_engine.config as config


def test_state_dir_override(tmp_path, monkeypatch):
    override = tmp_path / "custom_state"
    monkeypatch.setenv("JOBINTEL_STATE_DIR", str(override))
    import importlib

    importlib.reload(config)

    assert config.STATE_DIR == override
    assert config.HISTORY_DIR == override / "history"
    assert config.RUN_METADATA_DIR == override / "runs"

    config.ensure_dirs()
    assert config.STATE_DIR.exists()
    assert config.HISTORY_DIR.exists()
    assert config.RUN_METADATA_DIR.exists()
