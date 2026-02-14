from __future__ import annotations

import importlib
import sqlite3
from pathlib import Path


def _reload_run_index(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("JOBINTEL_STATE_DIR", str(tmp_path / "state"))
    import ji_engine.config as config
    import ji_engine.state.run_index as run_index

    config = importlib.reload(config)
    run_index = importlib.reload(run_index)
    return run_index


def test_run_index_insert_and_list_ordering(tmp_path: Path, monkeypatch) -> None:
    run_index = _reload_run_index(tmp_path, monkeypatch)

    run_index.append_run_record(
        run_id="2026-02-14T12:00:00Z",
        candidate_id="local",
        git_sha="aaa111",
        status="success",
        created_at="2026-02-14T12:00:00Z",
        summary_path="state/runs/20260214T120000Z/run_summary.v1.json",
        health_path="state/runs/20260214T120000Z/run_health.v1.json",
    )
    run_index.append_run_record(
        run_id="2026-02-14T12:00:00Z",
        candidate_id="alice",
        git_sha="bbb222",
        status="partial",
        created_at="2026-02-14T12:00:00Z",
        summary_path="state/candidates/alice/runs/20260214T120000Z/run_summary.v1.json",
        health_path="state/candidates/alice/runs/20260214T120000Z/run_health.v1.json",
    )
    run_index.append_run_record(
        run_id="2026-02-14T12:30:00Z",
        candidate_id="local",
        git_sha="ccc333",
        status="failed",
        created_at="2026-02-14T12:30:00Z",
        summary_path="state/runs/20260214T123000Z/run_summary.v1.json",
        health_path="state/runs/20260214T123000Z/run_health.v1.json",
    )

    local_rows = run_index.list_runs_as_dicts(candidate_id="local", limit=10)
    assert [row["run_id"] for row in local_rows] == [
        "2026-02-14T12:30:00Z",
        "2026-02-14T12:00:00Z",
    ]
    assert all(row["candidate_id"] == "local" for row in local_rows)

    alice_rows = run_index.list_runs_as_dicts(candidate_id="alice", limit=10)
    assert len(alice_rows) == 1
    assert alice_rows[0]["candidate_id"] == "alice"
    assert alice_rows[0]["run_id"] == "2026-02-14T12:00:00Z"


def test_run_index_is_append_only_for_same_run_candidate(tmp_path: Path, monkeypatch) -> None:
    run_index = _reload_run_index(tmp_path, monkeypatch)
    run_index.append_run_record(
        run_id="2026-02-14T13:00:00Z",
        candidate_id="local",
        git_sha="sha1",
        status="success",
        created_at="2026-02-14T13:00:00Z",
        summary_path="state/runs/20260214T130000Z/run_summary.v1.json",
        health_path="state/runs/20260214T130000Z/run_health.v1.json",
    )
    run_index.append_run_record(
        run_id="2026-02-14T13:00:00Z",
        candidate_id="local",
        git_sha="sha2",
        status="failed",
        created_at="2026-02-14T13:00:00Z",
        summary_path="state/runs/20260214T130000Z/run_summary.v1.json",
        health_path="state/runs/20260214T130000Z/run_health.v1.json",
    )

    rows = run_index.list_runs_as_dicts(candidate_id="local", limit=10)
    assert len(rows) == 1
    # First row is preserved because inserts are append-only with INSERT OR IGNORE.
    assert rows[0]["git_sha"] == "sha1"
    assert rows[0]["status"] == "success"


def test_run_index_no_sensitive_columns(tmp_path: Path, monkeypatch) -> None:
    run_index = _reload_run_index(tmp_path, monkeypatch)
    db_path = run_index.ensure_schema()
    conn = sqlite3.connect(db_path)
    try:
        columns = conn.execute("PRAGMA table_info(run_index_v1)").fetchall()
    finally:
        conn.close()
    column_names = [column[1] for column in columns]
    assert column_names == [
        "run_id",
        "candidate_id",
        "git_sha",
        "status",
        "created_at",
        "summary_path",
        "health_path",
    ]
