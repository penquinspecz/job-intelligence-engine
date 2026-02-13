"""
SignalCraft
Copyright (c) 2026 Chris Menendez.
All Rights Reserved.
See LICENSE for permitted use.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol

from ji_engine.config import (
    DEFAULT_CANDIDATE_ID,
    RUN_METADATA_DIR,
    STATE_DIR,
    candidate_run_metadata_dir,
    candidate_state_dir,
    sanitize_candidate_id,
)

logger = logging.getLogger(__name__)


class RunRepository(Protocol):
    def list_run_dirs(self, *, candidate_id: str = DEFAULT_CANDIDATE_ID) -> List[Path]: ...

    def resolve_run_dir(self, run_id: str, *, candidate_id: str = DEFAULT_CANDIDATE_ID) -> Path: ...

    def list_run_metadata_paths(self, *, candidate_id: str = DEFAULT_CANDIDATE_ID) -> List[Path]: ...

    def resolve_run_metadata_path(self, run_id: str, *, candidate_id: str = DEFAULT_CANDIDATE_ID) -> Path: ...

    def resolve_run_artifact_path(
        self,
        run_id: str,
        relative_path: str,
        *,
        candidate_id: str = DEFAULT_CANDIDATE_ID,
    ) -> Path: ...

    def write_run_json(
        self,
        run_id: str,
        relative_path: str,
        payload: Dict[str, Any],
        *,
        candidate_id: str = DEFAULT_CANDIDATE_ID,
        sort_keys: bool = True,
    ) -> Path: ...

    def run_dir(self, run_id: str, candidate_id: str = DEFAULT_CANDIDATE_ID) -> Path: ...

    def get_run(self, run_id: str, candidate_id: str = DEFAULT_CANDIDATE_ID) -> Optional[Dict[str, Any]]: ...

    def list_runs(self, candidate_id: str = DEFAULT_CANDIDATE_ID, limit: int = 200) -> List[Dict[str, Any]]: ...

    def latest_run(self, candidate_id: str = DEFAULT_CANDIDATE_ID) -> Optional[Dict[str, Any]]: ...

    def rebuild_index(self, candidate_id: str = DEFAULT_CANDIDATE_ID) -> Dict[str, Any]: ...


@dataclass(frozen=True)
class _RunIndexEntry:
    run_id: str
    timestamp: str
    run_dir: Path
    index_path: Path
    payload: Dict[str, Any]


def _sanitize_run_id(run_id: str) -> str:
    return run_id.replace(":", "").replace("-", "").replace(".", "")


class FileSystemRunRepository(RunRepository):
    def __init__(self, legacy_runs_dir: Path = RUN_METADATA_DIR) -> None:
        self._legacy_runs_dir = legacy_runs_dir
        self._fallback_logged: set[str] = set()

    def _db_path(self, candidate_id: str) -> Path:
        return candidate_state_dir(candidate_id) / "run_index.sqlite"

    def _candidate_run_roots(self, candidate_id: str) -> List[Path]:
        roots: List[Path] = []
        namespaced = candidate_run_metadata_dir(candidate_id)
        roots.append(namespaced)
        if candidate_id == DEFAULT_CANDIDATE_ID and self._legacy_runs_dir != namespaced:
            roots.append(self._legacy_runs_dir)
        seen: set[Path] = set()
        unique_roots: List[Path] = []
        for root in roots:
            resolved = root.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            unique_roots.append(root)
        return unique_roots

    def run_dir(self, run_id: str, candidate_id: str = DEFAULT_CANDIDATE_ID) -> Path:
        safe_candidate = sanitize_candidate_id(candidate_id)
        safe_run = _sanitize_run_id(run_id)
        namespaced = candidate_run_metadata_dir(safe_candidate) / safe_run
        if namespaced.exists():
            return namespaced
        if safe_candidate == DEFAULT_CANDIDATE_ID:
            legacy = self._legacy_runs_dir / safe_run
            if legacy.exists():
                return legacy
        return namespaced

    # Compatibility seam methods kept for existing callers.
    def resolve_run_dir(self, run_id: str, *, candidate_id: str = DEFAULT_CANDIDATE_ID) -> Path:
        return self.run_dir(run_id, candidate_id=candidate_id)

    def list_run_dirs(self, *, candidate_id: str = DEFAULT_CANDIDATE_ID) -> List[Path]:
        runs = self.list_runs(candidate_id=candidate_id, limit=1000)
        run_dirs: List[Path] = []
        seen: set[Path] = set()
        for item in runs:
            run_id = item.get("run_id")
            if not isinstance(run_id, str) or not run_id.strip():
                continue
            path = self.resolve_run_dir(run_id, candidate_id=candidate_id)
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            run_dirs.append(path)
        return run_dirs

    def list_run_metadata_paths(self, *, candidate_id: str = DEFAULT_CANDIDATE_ID) -> List[Path]:
        paths_by_name: Dict[str, Path] = {}
        for root in self._candidate_run_roots(candidate_id):
            if not root.exists():
                continue
            for path in sorted(root.glob("*.json"), key=lambda p: p.name):
                if not path.is_file():
                    continue
                paths_by_name.setdefault(path.name, path)
        return [paths_by_name[name] for name in sorted(paths_by_name.keys())]

    def resolve_run_metadata_path(self, run_id: str, *, candidate_id: str = DEFAULT_CANDIDATE_ID) -> Path:
        safe_run = _sanitize_run_id(run_id)
        for root in self._candidate_run_roots(candidate_id):
            candidate = root / f"{safe_run}.json"
            if candidate.exists():
                return candidate
        return self._candidate_run_roots(candidate_id)[0] / f"{safe_run}.json"

    def resolve_run_artifact_path(
        self,
        run_id: str,
        relative_path: str,
        *,
        candidate_id: str = DEFAULT_CANDIDATE_ID,
    ) -> Path:
        run_root = self.resolve_run_dir(run_id, candidate_id=candidate_id).resolve()
        candidate = (run_root / relative_path).resolve()
        if run_root not in candidate.parents and candidate != run_root:
            raise ValueError("Invalid artifact path")
        return candidate

    def write_run_json(
        self,
        run_id: str,
        relative_path: str,
        payload: Dict[str, Any],
        *,
        candidate_id: str = DEFAULT_CANDIDATE_ID,
        sort_keys: bool = True,
    ) -> Path:
        out_path = self.resolve_run_artifact_path(run_id, relative_path, candidate_id=candidate_id)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=sort_keys), encoding="utf-8")
        return out_path

    def _read_index_json(self, path: Path) -> Optional[Dict[str, Any]]:
        if not path.exists() or not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict):
            return None
        return payload

    def _scan_runs_from_filesystem(self, candidate_id: str) -> List[_RunIndexEntry]:
        entries: Dict[str, _RunIndexEntry] = {}
        for root in self._candidate_run_roots(candidate_id):
            if not root.exists():
                continue
            for run_dir in sorted((p for p in root.iterdir() if p.is_dir()), key=lambda p: p.name):
                index_path = run_dir / "index.json"
                payload = self._read_index_json(index_path)
                if payload is None:
                    continue
                run_id = payload.get("run_id")
                if not isinstance(run_id, str) or not run_id.strip():
                    continue
                if run_id in entries:
                    continue
                timestamp = payload.get("timestamp")
                if not isinstance(timestamp, str) or not timestamp.strip():
                    timestamp = run_id
                entries[run_id] = _RunIndexEntry(
                    run_id=run_id,
                    timestamp=timestamp,
                    run_dir=run_dir,
                    index_path=index_path,
                    payload=payload,
                )
        ordered = sorted(entries.values(), key=lambda e: (e.timestamp, e.run_id), reverse=True)
        return ordered

    def _ensure_schema(self, conn: sqlite3.Connection) -> None:
        conn.executescript(
            """
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS run_index (
                candidate_id TEXT NOT NULL,
                run_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                run_dir TEXT NOT NULL,
                index_path TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                PRIMARY KEY (candidate_id, run_id)
            );
            CREATE INDEX IF NOT EXISTS idx_run_index_latest
                ON run_index(candidate_id, timestamp DESC, run_id DESC);
            """
        )

    def rebuild_index(self, candidate_id: str = DEFAULT_CANDIDATE_ID) -> Dict[str, Any]:
        safe_candidate = sanitize_candidate_id(candidate_id)
        db_path = self._db_path(safe_candidate)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = db_path.with_suffix(".tmp")
        if tmp_path.exists():
            tmp_path.unlink()

        entries = self._scan_runs_from_filesystem(safe_candidate)
        conn = sqlite3.connect(tmp_path)
        try:
            self._ensure_schema(conn)
            conn.execute("DELETE FROM run_index WHERE candidate_id = ?", (safe_candidate,))
            for entry in sorted(entries, key=lambda e: e.run_id):
                conn.execute(
                    """
                    INSERT OR REPLACE INTO run_index(
                        candidate_id, run_id, timestamp, run_dir, index_path, payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        safe_candidate,
                        entry.run_id,
                        entry.timestamp,
                        str(entry.run_dir),
                        str(entry.index_path),
                        json.dumps(entry.payload, sort_keys=True, separators=(",", ":")),
                    ),
                )
            conn.commit()
        finally:
            conn.close()
        os.replace(tmp_path, db_path)
        return {
            "candidate_id": safe_candidate,
            "db_path": str(db_path),
            "runs_indexed": len(entries),
        }

    def _read_rows(self, candidate_id: str, limit: int) -> List[Dict[str, Any]]:
        safe_candidate = sanitize_candidate_id(candidate_id)
        db_path = self._db_path(safe_candidate)
        if not db_path.exists():
            self.rebuild_index(safe_candidate)
        conn = sqlite3.connect(db_path)
        try:
            rows = conn.execute(
                """
                SELECT payload_json
                FROM run_index
                WHERE candidate_id = ?
                ORDER BY timestamp DESC, run_id DESC
                LIMIT ?
                """,
                (safe_candidate, limit),
            ).fetchall()
            return [json.loads(row[0]) for row in rows]
        finally:
            conn.close()

    def _read_one(self, candidate_id: str, run_id: str) -> Optional[Dict[str, Any]]:
        safe_candidate = sanitize_candidate_id(candidate_id)
        db_path = self._db_path(safe_candidate)
        if not db_path.exists():
            self.rebuild_index(safe_candidate)
        conn = sqlite3.connect(db_path)
        try:
            row = conn.execute(
                """
                SELECT payload_json
                FROM run_index
                WHERE candidate_id = ? AND run_id = ?
                LIMIT 1
                """,
                (safe_candidate, run_id),
            ).fetchone()
            if not row:
                return None
            return json.loads(row[0])
        finally:
            conn.close()

    def _fallback(self, candidate_id: str, reason: str) -> List[Dict[str, Any]]:
        safe_candidate = sanitize_candidate_id(candidate_id)
        marker = f"{safe_candidate}:{reason}"
        if marker not in self._fallback_logged:
            logger.warning(
                "run_index fallback to filesystem scan: reason=%s candidate_id=%s",
                reason,
                safe_candidate,
            )
            self._fallback_logged.add(marker)
        return [entry.payload for entry in self._scan_runs_from_filesystem(safe_candidate)]

    def list_runs(self, candidate_id: str = DEFAULT_CANDIDATE_ID, limit: int = 200) -> List[Dict[str, Any]]:
        safe_candidate = sanitize_candidate_id(candidate_id)
        bounded_limit = max(1, min(limit, 1000))
        try:
            rows = self._read_rows(safe_candidate, bounded_limit)
            if rows:
                return rows
            return self._fallback(safe_candidate, "index_empty")
        except (json.JSONDecodeError, OSError, sqlite3.DatabaseError, sqlite3.OperationalError):
            self.rebuild_index(safe_candidate)
            try:
                return self._read_rows(safe_candidate, bounded_limit)
            except (json.JSONDecodeError, OSError, sqlite3.DatabaseError, sqlite3.OperationalError):
                return self._fallback(safe_candidate, "index_read_failed")

    def latest_run(self, candidate_id: str = DEFAULT_CANDIDATE_ID) -> Optional[Dict[str, Any]]:
        rows = self.list_runs(candidate_id=candidate_id, limit=1)
        return rows[0] if rows else None

    def get_run(self, run_id: str, candidate_id: str = DEFAULT_CANDIDATE_ID) -> Optional[Dict[str, Any]]:
        safe_candidate = sanitize_candidate_id(candidate_id)
        try:
            payload = self._read_one(safe_candidate, run_id)
            if payload:
                return payload
        except (json.JSONDecodeError, OSError, sqlite3.DatabaseError, sqlite3.OperationalError):
            self.rebuild_index(safe_candidate)
            try:
                payload = self._read_one(safe_candidate, run_id)
                if payload:
                    return payload
            except (json.JSONDecodeError, OSError, sqlite3.DatabaseError, sqlite3.OperationalError):
                pass

        for entry in self._scan_runs_from_filesystem(safe_candidate):
            if entry.run_id == run_id:
                return entry.payload
        return None


def discover_candidates() -> List[str]:
    candidates = {DEFAULT_CANDIDATE_ID}
    root = STATE_DIR / "candidates"
    if root.exists():
        for path in root.iterdir():
            if not path.is_dir():
                continue
            try:
                candidates.add(sanitize_candidate_id(path.name))
            except ValueError:
                continue
    return sorted(candidates)
