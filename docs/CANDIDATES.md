# Candidate Registry (CLI Scaffold)

SignalCraft now includes a file-backed candidate registry scaffold for Milestone 24.

## Scope and Safety

- No authentication and no web UI are included in this phase.
- No URL/network resume/LinkedIn fetching is included in this phase.
- Candidate IDs are fail-closed and must match: `[a-z0-9_]{1,64}`.
- `candidate_id=local` remains the default and does not change single-user pipeline behavior.

## Storage Layout

- Effective state root:
  - default: `<repo>/state`
  - override: `JOBINTEL_STATE_DIR=<path>` or CLI `--state-dir <path>`
- Deterministic registry path: `<state_dir>/candidates/registry.json`
- Candidate profile: `<state_dir>/candidates/<candidate_id>/candidate_profile.json`
- Candidate text input artifact store (immutable): `<state_dir>/candidates/<candidate_id>/inputs/artifacts/*.json`
- Namespaced dirs created by scaffold:
  - `<state_dir>/candidates/<candidate_id>/runs`
  - `<state_dir>/candidates/<candidate_id>/history`
  - `<state_dir>/candidates/<candidate_id>/user_state`

## Commands

```bash
python scripts/candidates.py list --json
python scripts/candidates.py add <candidate_id> --display-name "Candidate Name" --json
python scripts/candidates.py validate --json
python scripts/candidates.py ingest-text <candidate_id> --resume-file ./resume.txt --linkedin-file ./linkedin.txt --json
```

Override state dir for one command:

```bash
python scripts/candidates.py --state-dir /tmp/signalcraft_state add alice --display-name "Alice" --json
```

## Schemas

- `schemas/candidate_profile.schema.v1.json`
- `schemas/candidate_registry.schema.v1.json`

## Text-Only Ingestion Contract (v0)

- Accepted fields:
  - `resume_text`
  - `linkedin_text`
  - `summary_text`
- Input mode:
  - pasted text (`--resume-text`, etc.) or local files (`--resume-file`, etc.)
  - no URL options and no network fetching
- Size limits (UTF-8 bytes):
  - `resume_text`: max 120000
  - `linkedin_text`: max 120000
  - `summary_text`: max 40000
- For each update:
  - profile text field is set in `candidate_profile.json`
  - immutable artifact is written under `inputs/artifacts/` with `sha256`, `captured_at_utc`, `size_bytes`
  - profile keeps pointer metadata under `text_input_artifacts`
- Run report provenance includes pointer-only metadata (`candidate_input_provenance`); raw text is not copied into run reports.
