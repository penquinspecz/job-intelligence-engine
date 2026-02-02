# Operations

## How to run

Local (recommended for debugging):

```bash
python scripts/run_daily.py --profiles cs --us_only --no_post --snapshot-only --offline
```

Docker (build runs tests):

```bash
docker build -t jobintel:local .
docker run --rm \
  -v "$PWD/data:/app/data" \
  -v "$PWD/state:/app/state" \
  --env-file .env \
  jobintel:local --profiles cs --us_only --no_post --snapshot-only --offline
```

CI:

```bash
make gate-ci
```

Deterministic gate (recommended):

```bash
make gate-truth
```

Fast local/PR gate (no Docker):

```bash
make gate-fast
```

Snapshot-only violations fail fast with exit code 2 and a message naming the provider.

## Input selection rules

Scoring input resolution is handled by `scripts/run_daily.py`:

- Default (no flags): requires `data/openai_enriched_jobs.json`.
- `--no_enrich`: uses `data/openai_enriched_jobs.json` only if it exists and is newer than `data/openai_labeled_jobs.json`; otherwise falls back to labeled.
- `--ai`: runs AI augment and adds `--prefer_ai` when scoring, but still follows the same input selection as above.
- `--ai_only`: requires `data/openai_enriched_jobs_ai.json` and fails if missing.
- `--prefer_ai`: passed to `score_jobs.py` only when `--ai` or `--ai_only` is set by `run_daily.py`.

## Artifacts and where they live

Data outputs (`./data`):
- `openai_raw_jobs.json`
- `<provider_id>_raw_jobs.json` (per-provider raw output)
- `openai_labeled_jobs.json`
- `openai_enriched_jobs.json`
- `openai_enriched_jobs_ai.json` (if AI augment ran)
- `openai_ranked_jobs.<profile>.json`
- `openai_ranked_jobs.<profile>.csv`
- `openai_ranked_families.<profile>.json`
- `openai_shortlist.<profile>.md`

State (`./state`):
- `history/` per-run archived artifacts by profile
- `runs/` run metadata JSON
- `last_run.json` last run telemetry snapshot
- `user_state/` reserved for user-scoped state files

Run reports:
- `state/runs/<run_id>.json` (run metadata)
- Includes `run_report_schema_version`, inputs, outputs, scoring inputs, and selection reasons per profile.

## Replayability and verification

Replay a prior run (strict verification):

```bash
make replay RUN_ID=<run_id>
```

Or directly:

```bash
python scripts/replay_run.py --run-id <run_id> --profile cs --strict
```

Snapshot immutability check:

```bash
make verify-snapshots
```

Local replay gate (offline-safe):

```bash
make gate-replay
```

Exit codes:
- `0`: all checked artifacts match
- `2`: missing artifacts or mismatched hashes
- `>=3`: unexpected runtime errors

Replay JSON output:

```bash
python scripts/replay_run.py --run-id <run_id> --json
```

## Common failure modes and debugging

Exit codes:
- `0` success (including short-circuit runs)
- `2` validation/missing required inputs
- `>=3` runtime/provider failures (including subprocess stage failures)

Typical issues:
- Missing snapshot: ensure `data/openai_snapshots/index.html` exists.
- Missing input files: check `data/openai_labeled_jobs.json` and/or `data/openai_enriched_jobs.json` based on flags.
- AI-only missing: `--ai_only` requires `data/openai_enriched_jobs_ai.json`.
- Permission errors after Docker runs: fix ownership on `data/` and `state/` if needed.
- US-only filter removes all jobs: usually indicates missing/unnormalized locations; verify enrichment inputs.

Debug tips:
- Use `JOBINTEL_TEST_DEBUG_PATHS=1` to print temp paths in tests.
- Inspect `state/runs/*.json` for the inputs/outputs and hash provenance for a run.
- Providers are configured in `config/providers.json`; run `scripts/run_scrape.py --providers openai,anthropic` to scrape multiple providers.

## Docker daemon troubleshooting

If Docker commands fail with daemon `_ping` errors (e.g., HTTP 500), the daemon is unhealthy. Try:
- Restart Docker Desktop or the Docker daemon.
- Run `docker info` to confirm the daemon is reachable.
- Re-run `docker build` and the smoke command after the daemon recovers.

## User state

User state lives under `state/user_state/<profile>.json` and is used to annotate shortlist entries.

Examples:

```bash
python scripts/set_job_status.py --profile cs --job-id job_123 --status applied --note "Reached out."
python scripts/set_job_status.py --profile cs --url https://example.com/jobs/123 --status ignore
```

A “Quality Gates” section:

Developer default: `make gate` (alias for `gate-fast`).

Source-of-truth gate: `make gate-truth` (includes Docker no-cache).

CI uses `make gate-ci` (alias for `gate-truth`).

Order matters: pytest → snapshot immutability → replay smoke → Docker (truth gate only).

Snapshot behavior:

Providers may run in live or snapshot mode

Snapshots are first-class artifacts with:

atomic writes

sha256 verification

sidecar metadata

Determinism guarantees:

Snapshot + provider config + profile ⇒ deterministic output

Golden E2E tests enforce this
