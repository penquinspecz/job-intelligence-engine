import importlib
import os
import sys
from pathlib import Path

import ji_engine.config as config


def test_print_paths_reflect_env(tmp_path, monkeypatch, capsys):
    data_dir = tmp_path / "data"
    state_dir = tmp_path / "state"
    monkeypatch.setenv("JOBINTEL_DATA_DIR", str(data_dir))
    monkeypatch.setenv("JOBINTEL_STATE_DIR", str(state_dir))

    import scripts.run_daily as run_daily

    importlib.reload(config)
    importlib.reload(run_daily)

    monkeypatch.setattr(sys, "argv", ["run_daily.py", "--print_paths"])
    try:
        rc = run_daily.main()
        assert rc == 0
        out = capsys.readouterr().out
        assert f"DATA_DIR= {data_dir}" in out
        assert f"STATE_DIR= {state_dir}" in out
        assert f"HISTORY_DIR= {state_dir / 'history'}" in out
        assert f"RUN_METADATA_DIR= {state_dir / 'runs'}" in out
    finally:
        monkeypatch.delenv("JOBINTEL_DATA_DIR", raising=False)
        monkeypatch.delenv("JOBINTEL_STATE_DIR", raising=False)
        importlib.reload(config)
        importlib.reload(run_daily)
