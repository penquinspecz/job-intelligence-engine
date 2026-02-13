# Stash 0 Archive Receipt (2026-02-13)

Stash ref:
- stash@{0}: On codex/docs-roadmap-archive-restore: WIP safety stash before restoring main

Why stash was not applied:
- stash@{0} is revert-risk (deletion-heavy across docs/ops and mixed with core code drift).
- Added-files scan reported no A entries.
- Applying wholesale would risk reverting newer main behavior and documentation.

Extracted outcomes:
- Nugget A: provider registry provenance + tombstone guidance added additively to docs/OPERATIONS.md.
- Nugget B: provider candidates (airtable, canva, figma) deferred and recorded in docs/proof/stash0-nuggets-deferred-2026-02-13.md.

Process guarantees:
- No git stash apply, git stash pop, or git stash drop performed in this PR.
- No whole-file checkout from stash performed.
- No runtime/config semantics changes introduced.

Validation outputs:
- make format: PASS
- make lint: PASS
- PYTHONPATH=src ./.venv/bin/python -m pytest -q: PASS (539 passed, 15 skipped)
