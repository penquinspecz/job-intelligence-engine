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

Dependency lock workflow (source of truth):

- `requirements.txt` is generated, not hand-edited.
- Lock-generation tooling contract is pinned for CI/repro runs via `make tooling-sync` (`pip==25.0.1`, `pip-tools==7.4.1`).
- Update lockfiles with `make deps-sync`.
- Enforce parity with `make deps-check` (used in CI).
- If runtime dependencies change, update `pyproject.toml` first, then re-run `make deps-sync`.
- If local `pip`/`pip-tools` are incompatible, export falls back to deterministic installed-env resolution; run
  `make tooling-sync` to return to the pinned toolchain.
- Determinism check (optional): run `make deps-sync` twice and confirm no diff in `requirements.txt`.

Dashboard install/run (optional):
- Core install does not include dashboard runtime deps.
- Install dashboard runtime explicitly:

```bash
pip install -e ".[dashboard]"
```

- Run dashboard API:

```bash
make dashboard
```

If `fastapi`/`uvicorn` are missing, dashboard startup fails closed with a clear install command.

Kubernetes CronJob (portable, K8s-first):

Use the kustomize base at `ops/k8s/jobintel` or the AWS EKS overlay at
`ops/k8s/overlays/aws-eks` for IRSA + publish toggles. See `ops/k8s/README.md`
for the runtime contract and apply steps.

Deterministic gate (recommended):

```bash
make gate-truth
```

Fast local/PR gate (no Docker):

```bash
make gate-fast
```

Roadmap discipline guard:
- CI now runs a warn-only guard in `ci.yml`:
  - `.venv/bin/python scripts/check_roadmap_discipline.py`
- Local checks:

```bash
python scripts/check_roadmap_discipline.py
python scripts/check_roadmap_discipline.py --strict
```

Snapshot-only violations fail fast with exit code 2 and a message naming the provider.

## Provider failure policy

Live scraping is guarded by deterministic, fail-closed thresholds:
- Transient or unavailable error rate above `JOBINTEL_PROVIDER_ERROR_RATE_MAX` (default `0.25`) fails the run.
- Parsed job count below `JOBINTEL_PROVIDER_MIN_JOBS` (default `1`) in live mode fails the run.
- Parsed job count below `JOBINTEL_PROVIDER_MIN_SNAPSHOT_RATIO` (default `0.2`) of the snapshot baseline fails the run
  (when a baseline count is available).

These outcomes are recorded under `provenance_by_provider[*].failure_policy` in the run report and surfaced in Discord
run summaries (when enabled).

## Robots / policy handling

Live scraping enforces a robots/policy decision before any network fetch:

- Allowlist: `JOBINTEL_LIVE_ALLOWLIST_DOMAINS` (comma-separated) or provider-specific
  `JOBINTEL_LIVE_ALLOWLIST_DOMAINS_<PROVIDER>` controls which hosts are permitted for live fetches.
  If the allowlist is set and a host is not listed, live scraping is skipped and the run falls back to snapshots.
- Robots: the runner fetches `https://<host>/robots.txt` and evaluates `User-agent` rules using a consistent
  `JOBINTEL_USER_AGENT` (default: `jobintel-bot/1.0 (+https://github.com/penquinspecz/job-intelligence-engine)`).
  Disallow or fetch failures are treated conservatively (live skipped → snapshot fallback).

Every decision is logged as `[provider_retry][robots] ...` and recorded in provenance:
`robots_fetched`, `robots_allowed`, `allowlist_allowed`, `robots_final_allowed`, `robots_reason`, `robots_url`.

To override for dev/test, set:

```bash
export JOBINTEL_LIVE_ALLOWLIST_DOMAINS="jobs.ashbyhq.com"
```

## Discord diff gating

Discord run summaries are diff-gated by default:
- Post only when diffs exist (new/changed/removed) or the run fails.
- Override with `JOBINTEL_DISCORD_ALWAYS_POST=1` to always post a summary.
- `--no_post` still suppresses posting entirely.
- Summaries use identity-based deltas (`job_id` first, provider identity fallback) and include top new/changed items.
- Tune summary detail with `JOBINTEL_DISCORD_DIFF_TOP_N` (default `5`).

## Redaction enforcement

Secret scanning runs on proof bundles by default (fail-closed unless `--allow-secrets` is passed to the proof wrapper).

Run report and diff artifact writes support opt-in fail-closed mode:

```bash
export REDACTION_ENFORCE=1
python scripts/run_daily.py --profiles cs --us_only --no_post --snapshot-only --offline
```

With `REDACTION_ENFORCE=1`, secret-like patterns in generated JSON/markdown artifacts raise an error instead of only warning.

## Identity diff artifacts

Each run writes deterministic identity delta artifacts under `state/runs/<run_id>/`:

- `diff.json`: provider/profile diff payload with `added`, `changed`, `removed` buckets.
- `diff.md`: human-readable summary from the same payload.

Identity semantics:
- `new`: `job_id` not present in the prior run.
- `changed`: same identity, but one or more tracked fields changed:
  `title`, `location`, `team`, `level`, `score`, `jd_hash`.
- `removed`: identity present in prior run but not current run.

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
- `history/<profile>/runs/<run_id>/pointer.json` canonical run pointer to `state/runs/<run_id-sanitized>/`
- `history/<profile>/runs/<run_id>/identity_map.json` deterministic per-run identity map (compact `job_id` keyed view)
- `history/<profile>/runs/<run_id>/provenance.json` deterministic per-run scrape/provenance summary for that profile
- `history/<profile>/daily/<YYYY-MM-DD>/pointer.json` canonical day pointer to selected run_id
- `history/<profile>/retention.json` active retention settings for profile pointer pruning
- `runs/` run metadata JSON
- `last_run.json` last run telemetry snapshot
- `user_state/` reserved for user-scoped state files

Run reports:
- `state/runs/<run_id>.json` (run metadata)
- Includes `run_report_schema_version`, inputs, outputs, scoring inputs, and selection reasons per profile.

Run ID in logs:
- Every run prints a machine-parseable line early: `JOBINTEL_RUN_ID=<run_id>`.
- Use this as the canonical run_id for orchestrators and log parsers.

Success pointer:
- `state/last_success.json` is updated only on successful runs.
- It includes `run_id`, completion timestamp, provider/profile summaries, and key artifact hashes.

History retention controls:
- Disabled by default (safe): `HISTORY_ENABLED=0` unless explicitly set.
- Enable deterministic pointer retention: `HISTORY_ENABLED=1`
- Tune limits:
  - `HISTORY_KEEP_RUNS` (default `30`)
  - `HISTORY_KEEP_DAYS` (default `90`)
- CLI overrides:
  - `--history-enabled`
  - `--history-keep-runs <N>`
  - `--history-keep-days <D>`

Machine-parseable history logs:
- `HISTORY_RETENTION enabled=<0|1> ... run_id=<run_id>`
- Per profile on success:
  - `HISTORY_RETENTION profile=<profile> run_id=<run_id> enabled=1 keep_runs=<N> keep_days=<D> runs_kept=<n> runs_pruned=<n> daily_kept=<n> daily_pruned=<n> identity_count=<n> identity_map=<path> provenance=<path> run_pointer=<path> daily_pointer=<path>`

Inspect history identity/provenance artifacts:

```bash
cat state/history/<profile>/runs/<run_id>/identity_map.json
cat state/history/<profile>/runs/<run_id>/provenance.json
```

## Replayability and verification

Replay a prior run (strict verification):

```bash
make replay RUN_ID=<run_id>
```

Or directly:

```bash
python scripts/replay_run.py --run-id <run_id> --profile cs --strict
```

Replay with recompute (archived inputs → regenerated outputs):

```bash
python scripts/replay_run.py --run-id <run_id> --profile cs --strict --recalc
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

User state lives under `state/user_state/<profile>.json` and uses schema:

```json
{
  "schema_version": 1,
  "jobs": {
    "<job_id>": {
      "status": "ignore|saved|applied|interviewing",
      "date": "YYYY-MM-DD",
      "notes": "optional"
    }
  }
}
```

Semantics:
- `ignore`: suppress from shortlist and suppress from diff/Discord notifications.
- `applied` / `interviewing`: keep in shortlist with annotation, suppress from `new` notifications.
- `saved`: keep in shortlist with annotation; notifications allowed.

Invalid user-state JSON/schema is fail-closed for overlays (pipeline continues, warning is logged).

Examples:

```bash
python scripts/user_state.py add-status --profile cs --job-id job_123 --status applied --notes "Reached out."
python scripts/user_state.py add-status --profile cs --url https://example.com/jobs/123 --status ignore
python scripts/user_state.py list --profile cs
python scripts/user_state.py export --profile cs --out /tmp/user_state.cs.json
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
