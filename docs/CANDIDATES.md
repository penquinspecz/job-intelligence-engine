# Candidate Registry (CLI Scaffold)

SignalCraft now includes a file-backed candidate registry scaffold for Milestone 24.

## Scope and Safety

- No authentication and no web UI are included in this phase.
- No resume/LinkedIn ingestion is included in this phase.
- Candidate IDs are fail-closed and must match: `[a-z0-9_]{1,64}`.
- `candidate_id=local` remains the default and does not change single-user pipeline behavior.

## Storage Layout

- Registry: `state/candidates/registry.json`
- Candidate profile: `state/candidates/<candidate_id>/candidate_profile.json`
- Namespaced dirs created by scaffold:
  - `state/candidates/<candidate_id>/runs`
  - `state/candidates/<candidate_id>/history`
  - `state/candidates/<candidate_id>/user_state`

## Commands

```bash
python scripts/candidates.py list --json
python scripts/candidates.py add <candidate_id> --display-name "Candidate Name" --json
python scripts/candidates.py validate --json
```

## Schemas

- `schemas/candidate_profile.schema.v1.json`
- `schemas/candidate_registry.schema.v1.json`
