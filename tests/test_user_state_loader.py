import json
from pathlib import Path

import pytest

from ji_engine.utils.user_state import load_user_state


def test_load_user_state_returns_empty_when_missing(tmp_path: Path) -> None:
    missing = tmp_path / "user_state.json"
    assert load_user_state(missing) == {}


def test_load_user_state_reads_schema_json(tmp_path: Path) -> None:
    path = tmp_path / "user_state.json"
    payload = {"schema_version": 1, "jobs": {"job-a": {"status": "saved"}}}
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert load_user_state(path) == {"job-a": {"status": "saved"}}


def test_load_user_state_reads_legacy_map(tmp_path: Path) -> None:
    path = tmp_path / "user_state.json"
    payload = {"job-a": {"status": "saved"}}
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert load_user_state(path) == payload


def test_load_user_state_rejects_invalid_schema(tmp_path: Path) -> None:
    path = tmp_path / "user_state.json"
    path.write_text(json.dumps({"seen_jobs": ["a", "b"]}), encoding="utf-8")
    with pytest.raises(ValueError, match="invalid user_state schema"):
        load_user_state(path)
