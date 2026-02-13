# Milestone 13 Proof - Run Indexing v1 (2026-02-13)

## Scope
- Added candidate-aware SQLite metadata index under state.
- Kept artifacts as filesystem blobs; SQLite stores run metadata only.
- Dashboard run listing/latest paths now resolve through `RunRepository` index-first behavior.
- Added deterministic rebuild tooling (`scripts/rebuild_run_index.py`).

## Index File Location
- Default candidate (`local`): `state/candidates/local/run_index.sqlite`
- Other candidates: `state/candidates/<candidate_id>/run_index.sqlite`
- Candidate data roots remain isolated:
  - `state/candidates/<candidate_id>/runs`
  - `state/candidates/<candidate_id>/history`
  - `state/candidates/<candidate_id>/user_state`
- Backward-compat for `local` reads:
  - prefer namespaced runs root first
  - fallback to legacy `state/runs` when needed

## Index Schema Contract (v1)
Implementation source: `src/ji_engine/run_repository.py` (`_ensure_schema`).

- Table: `run_index`
- Columns:
  - `candidate_id TEXT NOT NULL`
  - `run_id TEXT NOT NULL`
  - `timestamp TEXT NOT NULL`
  - `run_dir TEXT NOT NULL`
  - `index_path TEXT NOT NULL`
  - `payload_json TEXT NOT NULL`
- Primary key: `(candidate_id, run_id)`
- Read-order index: `idx_run_index_latest(candidate_id, timestamp DESC, run_id DESC)`
- Current schema versioning model:
  - v1 is code-defined (SQL contract above)
  - index is rebuildable from artifacts, so compatibility is governed by rebuild contract rather than migrations

## Rebuild Guarantees
- Rebuild source of truth is on-disk run artifacts (`index.json` per run dir), not prior SQLite content.
- Filesystem scan order is deterministic (sorted by directory name).
- Insert order into SQLite is deterministic (sorted by `run_id`).
- Stored `payload_json` is deterministically encoded (`sort_keys=True`, stable separators).
- Rebuild is atomic (`*.tmp` then `os.replace`) to avoid partial-write index states.

## Corrupt Index Behavior
- Read path (`list_runs` / `get_run`) attempts index read first.
- On index read errors (`sqlite3.*`, JSON decode, I/O):
  - rebuild index first
  - retry index read
  - if still failing, fallback to deterministic filesystem scan and log warning
- This behavior is fail-safe for availability while preserving deterministic ordering.

## Candidate Isolation
- Index file is per-candidate under candidate namespace.
- Same `run_id` across candidates does not collide:
  - distinct DB files
  - candidate-filtered query paths
- Covered by tests: `tests/test_run_repository.py::test_candidate_isolation_same_run_id`

## Perf Sanity (Rough Local Measurement)
Environment: local laptop, Python 3.12 venv, temporary state dir, synthetic `800` unique run dirs.

- Filesystem scan only (`_scan_runs_from_filesystem`): `~30.18 ms`
- Index-cold list (`list_runs`, includes rebuild + first query): `~31.22 ms`
- Index-warm list (`list_runs`, existing DB): `~0.59 ms`
- Corrupt index recovery (`list_runs` after DB corruption): `~32.66 ms`

Interpretation:
- Cold path is roughly equivalent to a full scan (as expected, rebuild work dominates).
- Warm path significantly reduces common run-listing latency.
- Corrupt index path remains bounded and self-healing via rebuild-first logic.

## Tests Added / Relevant
- `tests/test_run_repository.py`
  - deterministic rebuild behavior
  - candidate isolation for same `run_id`
  - latest lookup index path (no forced scan)
  - corrupt index triggers safe rebuild
  - rebuild CLI smoke
- `tests/test_dashboard_app.py`
  - candidate isolation in `/runs`
  - invalid `candidate_id` fail-closed (`400`)
  - local latest path backward compatibility

## Validation Receipts
- `make format`
- `make lint`
- `PYTHONPATH=src ./.venv/bin/python -m pytest -q`
