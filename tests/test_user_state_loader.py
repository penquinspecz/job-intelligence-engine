import json
from pathlib import Path

from ji_engine.utils.user_state import load_user_state


def test_load_user_state_returns_empty_when_missing(tmp_path: Path) -> None:
    missing = tmp_path / "user_state.json"
    assert load_user_state(missing) == {}


def test_load_user_state_reads_json(tmp_path: Path) -> None:
    path = tmp_path / "user_state.json"
    payload = {"seen_jobs": ["a", "b"]}
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert load_user_state(path) == payload
