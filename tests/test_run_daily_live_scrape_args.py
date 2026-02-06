from __future__ import annotations

import importlib
import sys
from pathlib import Path

import ji_engine.config as config
import scripts.run_daily as run_daily_module


def test_live_scrape_adds_snapshot_write_dir(tmp_path, monkeypatch) -> None:
    data_dir = tmp_path / "data"
    state_dir = tmp_path / "state"
    snapshot_dir = data_dir / "openai_snapshots"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    (snapshot_dir / "index.html").write_text("<html>ok</html>", encoding="utf-8")

    monkeypatch.setenv("JOBINTEL_DATA_DIR", str(data_dir))
    monkeypatch.setenv("JOBINTEL_STATE_DIR", str(state_dir))
    monkeypatch.setenv("CAREERS_MODE", "LIVE")
    snap_write = tmp_path / "snapshots"
    monkeypatch.setenv("JOBINTEL_SNAPSHOT_WRITE_DIR", str(snap_write))

    importlib.reload(config)
    run_daily = importlib.reload(run_daily_module)

    captured = {}

    def fake_run(cmd, *, stage: str):
        captured["cmd"] = cmd
        return None

    monkeypatch.setattr(run_daily, "_run", fake_run)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_daily.py",
            "--no_subprocess",
            "--scrape_only",
            "--providers",
            "openai",
            "--profiles",
            "cs",
        ],
    )

    rc = run_daily.main()
    assert rc == 0

    cmd = captured.get("cmd") or []
    assert "--snapshot-write-dir" in cmd
    idx = cmd.index("--snapshot-write-dir")
    assert Path(cmd[idx + 1]) == snap_write
    assert snap_write.exists()


def test_live_scrape_default_snapshot_write_dir_uses_tmp(tmp_path, monkeypatch) -> None:
    data_dir = tmp_path / "data"
    state_dir = tmp_path / "state"
    snapshot_dir = data_dir / "openai_snapshots"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    (snapshot_dir / "index.html").write_text("<html>ok</html>", encoding="utf-8")

    monkeypatch.setenv("JOBINTEL_DATA_DIR", str(data_dir))
    monkeypatch.setenv("JOBINTEL_STATE_DIR", str(state_dir))
    monkeypatch.setenv("CAREERS_MODE", "LIVE")
    monkeypatch.delenv("JOBINTEL_SNAPSHOT_WRITE_DIR", raising=False)

    importlib.reload(config)
    run_daily = importlib.reload(run_daily_module)

    captured = {}

    def fake_run(cmd, *, stage: str):
        captured["cmd"] = cmd
        return None

    monkeypatch.setattr(run_daily, "_run", fake_run)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_daily.py",
            "--no_subprocess",
            "--scrape_only",
            "--providers",
            "openai",
            "--profiles",
            "cs",
        ],
    )

    rc = run_daily.main()
    assert rc == 0
    cmd = captured.get("cmd") or []
    assert "--snapshot-write-dir" in cmd
    idx = cmd.index("--snapshot-write-dir")
    assert Path(cmd[idx + 1]).as_posix().startswith("/tmp/")
