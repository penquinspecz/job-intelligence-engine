"""
SignalCraft
Copyright (c) 2026 Chris Menendez.
All Rights Reserved.
See LICENSE for permitted use.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from ji_engine.config import DEFAULT_CANDIDATE_ID, STATE_DIR, sanitize_candidate_id

SCHEMA_VERSION = 1
RUN_INDEX_FILENAME = "run_index.sqlite3"


@dataclass(frozen=True)
class RunIndexRow:
    run_id: str
    candidate_id: Optional[str]
    git_sha: Optional[str]
    status: str
    created_at: str
    summary_path: Optional[str]
    health_path: Optional[str]


def run_index_path() -> Path:
    return STATE_DIR / RUN_INDEX_FILENAME


def _candidate_to_db_value(candidate_id: Optional[str]) -> Optional[str]:
    if candidate_id is None:
        return None
    safe = sanitize_candidate_id(candidate_id)
    if safe == DEFAULT_CANDIDATE_ID:
        return None
    return safe


def _candidate_from_db_value(candidate_id: Optional[str]) -> str:
    if candidate_id in {None, ""}:
        return DEFAULT_CANDIDATE_ID
    return candidate_id


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn


def ensure_schema(db_path: Optional[Path] = None) -> Path:
    path = db_path or run_index_path()
    conn = _connect(path)
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS run_index_meta(
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS run_index_v1(
                run_id TEXT NOT NULL,
                candidate_id TEXT NULL,
                git_sha TEXT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                summary_path TEXT NULL,
                health_path TEXT NULL,
                PRIMARY KEY(run_id, candidate_id)
            );
            CREATE UNIQUE INDEX IF NOT EXISTS uq_run_index_v1_run_candidate
                ON run_index_v1(run_id, ifnull(candidate_id, ''));
            CREATE INDEX IF NOT EXISTS idx_run_index_v1_latest
                ON run_index_v1(created_at DESC, run_id DESC);
            CREATE INDEX IF NOT EXISTS idx_run_index_v1_candidate_latest
                ON run_index_v1(candidate_id, created_at DESC, run_id DESC);
            """
        )
        conn.execute(
            "INSERT OR REPLACE INTO run_index_meta(key, value) VALUES('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )
        conn.commit()
    finally:
        conn.close()
    return path


def append_run_record(
    *,
    run_id: str,
    candidate_id: str,
    git_sha: Optional[str],
    status: str,
    created_at: str,
    summary_path: Optional[str],
    health_path: Optional[str],
    db_path: Optional[Path] = None,
) -> Path:
    path = ensure_schema(db_path)
    conn = _connect(path)
    try:
        conn.execute(
            """
            INSERT OR IGNORE INTO run_index_v1(
                run_id, candidate_id, git_sha, status, created_at, summary_path, health_path
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                _candidate_to_db_value(candidate_id),
                git_sha,
                status,
                created_at,
                summary_path,
                health_path,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return path


def list_runs(
    *,
    candidate_id: Optional[str] = DEFAULT_CANDIDATE_ID,
    limit: int = 20,
    db_path: Optional[Path] = None,
) -> List[RunIndexRow]:
    safe_limit = max(1, min(int(limit), 500))
    path = ensure_schema(db_path)
    candidate_db = _candidate_to_db_value(candidate_id) if candidate_id is not None else None

    conn = _connect(path)
    try:
        if candidate_id is None:
            rows = conn.execute(
                """
                SELECT run_id, candidate_id, git_sha, status, created_at, summary_path, health_path
                FROM run_index_v1
                ORDER BY created_at DESC, run_id DESC
                LIMIT ?
                """,
                (safe_limit,),
            ).fetchall()
        elif candidate_db is None:
            rows = conn.execute(
                """
                SELECT run_id, candidate_id, git_sha, status, created_at, summary_path, health_path
                FROM run_index_v1
                WHERE candidate_id IS NULL
                ORDER BY created_at DESC, run_id DESC
                LIMIT ?
                """,
                (safe_limit,),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT run_id, candidate_id, git_sha, status, created_at, summary_path, health_path
                FROM run_index_v1
                WHERE candidate_id = ?
                ORDER BY created_at DESC, run_id DESC
                LIMIT ?
                """,
                (candidate_db, safe_limit),
            ).fetchall()
    finally:
        conn.close()

    output: List[RunIndexRow] = []
    for row in rows:
        output.append(
            RunIndexRow(
                run_id=row["run_id"],
                candidate_id=_candidate_from_db_value(row["candidate_id"]),
                git_sha=row["git_sha"],
                status=row["status"],
                created_at=row["created_at"],
                summary_path=row["summary_path"],
                health_path=row["health_path"],
            )
        )
    return output


def list_runs_as_dicts(
    *,
    candidate_id: Optional[str] = DEFAULT_CANDIDATE_ID,
    limit: int = 20,
    db_path: Optional[Path] = None,
) -> List[Dict[str, Optional[str]]]:
    rows = list_runs(candidate_id=candidate_id, limit=limit, db_path=db_path)
    return [
        {
            "run_id": row.run_id,
            "candidate_id": row.candidate_id,
            "git_sha": row.git_sha,
            "status": row.status,
            "created_at": row.created_at,
            "summary_path": row.summary_path,
            "health_path": row.health_path,
        }
        for row in rows
    ]
