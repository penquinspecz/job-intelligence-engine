from __future__ import annotations

import importlib
import os
from pathlib import Path
from typing import Any


def test_warns_on_non_writable_artifacts(monkeypatch: Any, tmp_path: Path, caplog: Any) -> None:
    """
    Simulate root-owned / non-writable artifacts (e.g., created by Docker) and ensure
    run_daily emits a clear WARNING without failing.

    Cross-platform: we simulate non-writable via monkeypatching os.access instead of chmod.
    """
    import scripts.run_daily as run_daily

    run_daily = importlib.reload(run_daily)

    bad = tmp_path / "data" / "openai_labeled_jobs.json"
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_text("[]", encoding="utf-8")

    real_access = os.access

    def fake_access(path: str, mode: int) -> bool:
        if Path(path) == bad and mode == os.W_OK:
            return False
        return real_access(path, mode)

    monkeypatch.setattr(run_daily.os, "access", fake_access)

    caplog.set_level("WARNING")
    run_daily._warn_if_not_user_writable([bad], context="test")

    assert "Non-writable pipeline artifacts detected" in caplog.text
    assert "Fix ownership/permissions" in caplog.text

