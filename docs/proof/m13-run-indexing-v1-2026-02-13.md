# Milestone 13 Proof - Run Indexing v1 (2026-02-13)

## Scope
- Added candidate-aware SQLite run metadata index under state.
- Kept artifacts as filesystem blobs; SQLite stores metadata only.
- Refactored dashboard run listing/latest paths to use `RunRepository` index-first behavior.
- Added deterministic rebuild tooling (`scripts/rebuild_run_index.py`).

## Index Layout
- Local candidate DB: `state/candidates/local/run_index.sqlite`
- Non-local candidate DB: `state/candidates/<candidate_id>/run_index.sqlite`
- Local read compatibility:
  - Prefer `state/candidates/local/runs`
  - Fall back to legacy `state/runs` when needed

## Rebuild + Determinism
- Rebuild scans run directories in sorted order.
- Inserts are deterministic (`run_id` sorted) and query ordering is deterministic (`timestamp DESC, run_id DESC`).
- Index can be recreated from `index.json` artifacts only.

## Safety and Fallback
- Corrupt/missing SQLite index triggers deterministic rebuild.
- If rebuild/query still fails, dashboard/repository falls back to filesystem scan and logs explicit warning.

## Tests Added
- `tests/test_run_repository.py`
  - Deterministic rebuild behavior
  - Candidate isolation for same `run_id`
  - Latest lookup uses index path
  - Corrupt index safe fallback
  - CLI rebuild smoke
- `tests/test_dashboard_app.py`
  - Candidate isolation in `/runs`
  - Invalid `candidate_id` fail-closed (400)
  - Local latest path remains backward compatible

## Validation Receipts
- `make format`
- `make lint`
- `PYTHONPATH=src ./.venv/bin/python -m pytest -q`
