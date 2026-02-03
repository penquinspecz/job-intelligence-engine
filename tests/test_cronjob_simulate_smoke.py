from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_cronjob_simulate_smoke(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    state_dir = tmp_path / "state"
    data_dir.mkdir(parents=True, exist_ok=True)
    state_dir.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env.update(
        {
            "JOBINTEL_DATA_DIR": str(data_dir),
            "JOBINTEL_STATE_DIR": str(state_dir),
            "JOBINTEL_CRONJOB_RUN_ID": "2026-01-01T00:00:00Z",
            "CAREERS_MODE": "SNAPSHOT",
            "EMBED_PROVIDER": "stub",
            "ENRICH_MAX_WORKERS": "1",
            "DISCORD_WEBHOOK_URL": "",
        }
    )
    result = subprocess.run(
        [sys.executable, "scripts/cronjob_simulate.py"],
        check=False,
        env=env,
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
