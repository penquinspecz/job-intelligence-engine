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

Determinism parity preflight (local and CI-friendly):

```bash
make doctor
```

GitHub CLI reliability (flaky DNS/API environments):

```bash
gh pr checks <pr-number> --watch
make gh-checks PR=<pr-number>
scripts/gh_retry.sh pr merge <pr-number> --merge --delete-branch
```

Strict escalation ladder:

1. Plain `gh` (fast path)
   - Use direct commands first:
     - `gh pr view <pr-number>`
     - `gh pr checks <pr-number> --watch`
2. Bounded retry wrapper
   - Retry only transient DNS/network faults:
     - `scripts/gh_retry.sh pr checks <pr-number> --watch`
     - `make gh-checks PR=<pr-number>`
   - Retry controls:
     - `GH_RETRY_MAX_ATTEMPTS` (default `4`)
     - `GH_RETRY_SLEEP_SECONDS` (default `2`)
   - Non-network failures (bad args, permissions, red checks) fail immediately.
3. Elevated network execution
   - If step 2 still fails with DNS/API errors, re-run the exact same command in elevated network mode.
   - Keep command text unchanged; only execution mode changes.
4. Manual browser fallback
   - PR create URL: `https://github.com/penquinspecz/SignalCraft/pull/new/<branch>`
   - PR checks page: open the PR in browser and verify required checks are green before merge.

Failure symptoms that should trigger escalation:
- `gh`: `error connecting to api.github.com`
- `curl`/`git`: `Could not resolve host: github.com`

`make doctor` fails closed for:
- dirty git status
- detached current worktree or `main` checked out in multiple worktrees
- missing/mismatched `.venv` against `.python-version`
  - runtime pin: `.python-version` is `3.14.3`
- missing CI parity contract files (`docs/DETERMINISM_CONTRACT.md`, `docs/RUN_REPORT.md`, `config/scoring.v1.json`, `schemas/run_health.schema.v1.json`)
- missing offline test harness defaults/marker wiring (`tests/conftest.py`, `pytest.ini`, `aws_integration`)
- non-renderable `onprem-pi` overlay via `scripts/k8s_render.py --overlay onprem-pi --stdout --limit 40`

Doctor informational warnings:
- prints `JOBINTEL_STATE_DIR` if set
- warns when `JOBINTEL_STATE_DIR` points inside the repo (to avoid mixing source + runtime state)

CI smoke gate contract and failure-mode diagnostics:
- `docs/CI_SMOKE_GATE.md`

Dependency lock workflow (source of truth):

- `requirements.txt` is generated, not hand-edited.
- Lock-generation tooling contract is pinned for CI/repro runs via `make tooling-sync` (`pip==25.0.1`, `pip-tools==7.4.1`).
- Update lockfiles with `make deps-sync`.
- Enforce parity with `make deps-check` (used in CI).
- If runtime dependencies change, update `pyproject.toml` first, then re-run `make deps-sync`.
- Export policy is explicit: `pip-compile` is invoked with `--strip-extras` so lock output does not depend on
  pip-tools default changes.
- CI strict mode (`GITHUB_ACTIONS=true` / `JIE_DEPS_TARGET=ci`) is fail-closed: if `pip-compile` fails, `deps-check`
  fails (no fallback).
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

Candidate setup and registry (Milestone 24 scaffold):
- See `docs/CANDIDATES.md` for storage layout and safety constraints.
- CLI commands:

```bash
python scripts/candidates.py list --json
python scripts/candidates.py add alice --display-name "Alice Example" --json
python scripts/candidates.py validate --json
```

State root override for candidate operations:

```bash
python scripts/candidates.py --state-dir /path/to/state add alice --json
```

Candidate state contract (canonical layout):
- Candidate root: `state/candidates/<candidate_id>/`
- User inputs: `inputs/candidate_profile.json`
- System state pointers: `system_state/{last_run.json,last_success.json,run_index.sqlite}`
- Derived artifacts: `{runs/,history/,user_state/,proofs/}`
- Canonical path resolution is implemented in `src/ji_engine/config.py` (`candidate_state_paths(...)`).

Backward compatibility policy (`candidate_id=local`):
- Reads prefer namespaced paths and then fall back to legacy global paths where required.
- Pointer writers keep legacy global pointer mirrors for `local` to avoid breaking existing consumers.
- Legacy candidate profile location (`state/candidates/<candidate_id>/candidate_profile.json`) remains readable.

Run metadata index (Milestone 13):
- Rebuild command: `scripts/rebuild_run_index.py`
- Default behavior rebuilds `candidate_id=local`.
- Use this after manual state repair, index corruption, or migration checks.

Local run index (SQLite, deterministic append-only metadata):
- Path: `state/run_index.sqlite3`
- Fields: `run_id`, `candidate_id`, `git_sha`, `status`, `created_at`, `summary_path`, `health_path`
- No raw job content and no candidate text is stored in this index.

List runs quickly from CLI:

```bash
python -m jobintel.cli runs list --candidate-id local --limit 20
```

Reset local run index (safe; artifacts remain source of truth):

```bash
rm -f state/run_index.sqlite3
```

Rebuild local candidate index:

```bash
python scripts/rebuild_run_index.py --json
```

Rebuild specific candidate index:

```bash
python scripts/rebuild_run_index.py --candidate-id alice --json
```

Rebuild all discovered candidate indexes:

```bash
python scripts/rebuild_run_index.py --all-candidates --json
```

Expected JSON fields per candidate:
- `candidate_id`
- `runs_indexed`
- `db_path`

Corrupt index behavior:
- Runtime read path attempts rebuild first.
- If rebuild/read still fails, repository falls back to deterministic filesystem scan and logs warning.

AI accounting (deterministic per run + candidate rollups):
- Per-run artifact: `state/runs/<run_id>/costs.json`
- Run report field: `ai_accounting`
- Candidate rollups:
  - `state/candidates/<candidate_id>/ai_accounting_daily.json`
  - `state/candidates/<candidate_id>/ai_accounting_weekly.json`

Per-run accounting fields include:
- `ai_tokens_in`
- `ai_tokens_out`
- `ai_estimated_tokens`
- `ai_estimated_cost_usd`
- `ai_accounting.model_usage[]` with model-specific totals

Pricing configuration (USD per 1K tokens):
- Global defaults:
  - `AI_COST_INPUT_PER_1K`
  - `AI_COST_OUTPUT_PER_1K`
- Optional model-specific overrides:
  - `AI_COST_INPUT_PER_1K_<MODEL_KEY>`
  - `AI_COST_OUTPUT_PER_1K_<MODEL_KEY>`
  where `<MODEL_KEY>` is uppercase model name with non-alphanumeric chars replaced by `_`.

Provider registry (Milestone 5 foundation):

- Canonical file: `config/providers.json` (schema: `schemas/providers.schema.v1.json`)
- Authoring workflow: `docs/PROVIDERS.md`
- Registry loader: `src/ji_engine/providers/registry.py`
- Authoring guide: `docs/PROVIDERS.md` ("add a provider in 10 minutes")
- Schema validation is enforced at load time (unknown keys fail closed).
- Provider selection resolver used by both:
  - `scripts/run_scrape.py`
  - `scripts/run_daily.py`
- `providers=all` resolves only providers with `enabled=true` (deterministic sort by `provider_id`).
- Run reports include provider registry provenance under
  `provenance.build.provider_registry` (schema version + registry hash).
- Supported extraction modes:
  - `ashby_api` (canonical config alias, normalized to runtime `ashby`)
  - `jsonld` (structured JobPosting JSON-LD parser)
  - `html_rules` (canonical config alias, normalized to runtime `html_list`)
  - `llm_fallback` (optional; requires `llm_fallback.enabled=true`)
  - Back-compat inputs (`ashby`, `snapshot_json`, `html_list`) remain accepted.

How to add a provider (deterministic path):

1. Add entry in `config/providers.json` under `providers[]`:
   - required: `provider_id`, `display_name`, `enabled`, `extraction_mode`, `careers_urls`
   - scrape mode + snapshots: `mode`, `snapshot_path` or `snapshot_dir`
   - capability flags: `live_enabled` (optional), `snapshot_enabled` (optional)
   - allowlist + cadence hints: `allowed_domains`, `update_cadence` (informational string or structured object)
   - politeness defaults/overrides:
     - `politeness.defaults` (provider-level defaults)
     - `politeness.host_overrides` (per-host override map)
     - back-compat flat keys still accepted (`min_delay_s`, `max_attempts`, etc.)
   - optional LLM fallback (cache-only, deterministic):
     - `llm_fallback.enabled=true` + `llm_fallback.cache_dir` (required)
     - `llm_fallback.temperature=0` (enforced)
2. Add/update snapshot fixture under `data/<provider_id>_snapshots/`.
   - Scaffold quickly:
     - `make provider-scaffold provider=<provider_id>`
     - `make provider-template provider=<provider_id>`
   - Snapshot-only first:
     - `mode: "snapshot"`
     - `live_enabled: false`
     - explicit `allowed_domains`
   - CI enforces snapshot fixture existence for enabled snapshot providers.
   - If snapshot bytes changed intentionally, run:
     `make provider-manifest-update provider=<provider_id>`
   - PR body must state: `snapshot manifest update required: yes|no` when `config/providers.json` changes.
   - To retire a provider without deleting history, set `enabled=false` and populate
     `tombstone` metadata (`tombstone.reason` required; `ticket`, `replaced_by`,
     `removed_at` optional).
3. Run scrape in snapshot mode:

```bash
python scripts/run_scrape.py --providers <provider_id> --providers-config config/providers.json --mode SNAPSHOT
```

4. Verify deterministic output:
   - `data/ashby_cache/<provider_id>_raw_jobs.json`
   - `data/ashby_cache/<provider_id>_scrape_meta.json`

Proof-of-design provider in-tree:
- `perplexity` (`jsonld`, snapshot-first)
- Snapshot fixture: `data/perplexity_snapshots/index.html`

Snapshot validation semantics (no footguns):
- `jobintel snapshots validate --provider <id>` validates only the requested providers.
- `jobintel snapshots validate --all` validates only providers with snapshots present on disk,
  and skips missing snapshot paths to avoid false failures.

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

## Add Provider Checklist (M5)

1. **Config entry (required):**
   - `provider_id`, `extraction_mode`, and one of `careers_urls`/`careers_url`/`board_url`.
   - `snapshot_path` or `snapshot_dir` (defaults to `data/<provider_id>_snapshots/index.html`).
   - `snapshot_enabled: true` (default) unless intentionally disabled.
   - `allowed_domains` + `update_cadence` (optional but recommended).
2. **Fixture requirements (deterministic):**
   - Commit `data/<provider_id>_snapshots/index.html` (or JSON snapshot for `snapshot_json`).
   - Add a test fixture under `tests/fixtures/providers/<provider_id>/index.html`.
3. **Validation commands (offline):**
   - `python -m src.jobintel.cli snapshots validate --provider <id>`
   - `python -m src.jobintel.cli snapshots validate --all` (skips missing snapshot dirs)
4. **Tests to update/add:**
   - Registry schema rejection test (missing fields / unknown keys).
   - JSON-LD parsing test (stable ordering + stable `job_id` across runs).
   - Snapshot validation selection/skip semantics.
5. **Debug schema failures:**
   - Errors are fail-closed and name the missing field or bad key.
   - Check `schemas/providers.schema.v1.json` and `src/ji_engine/providers/registry.py`.
6. **LLM fallback (cache-only, disabled by default):**
   - `llm_fallback.enabled` is `false` unless explicitly configured.
   - If enabled, requires `llm_fallback.cache_dir` and `temperature=0`.

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
  `JOBINTEL_USER_AGENT` (default: `signalcraft-bot/1.0 (+https://github.com/penquinspecz/SignalCraft)`).
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

## Semantic Safety Net (M7, bounded and deterministic)

Semantic is deterministic and runs in one of two modes controlled by `SEMANTIC_MODE`:
- `sidecar` (default when `SEMANTIC_ENABLED=1`): compute semantic evidence only; does not mutate ranked outputs.
- `boost`: apply bounded semantic boost to scoring output.

When `SEMANTIC_MODE=boost`, final score contract is:
- `final_score = clamp(base_score + semantic_boost, 0, 100)`
- `semantic_boost` is bounded in `[0, SEMANTIC_MAX_BOOST]`
- If semantic is disabled/unavailable, or mode is `sidecar`, ranked outputs must match pre-semantic behavior exactly.

Environment flags:
- `SEMANTIC_ENABLED=1` enables semantic processing (default off).
- `SEMANTIC_MODE` selects semantic behavior: `sidecar` or `boost` (default `sidecar`).
- `SEMANTIC_MODEL_ID` selects model id (default `deterministic-hash-v1`).
- `SEMANTIC_MAX_JOBS` bounds per-run embedding workload (default `200`).
- `SEMANTIC_TOP_K` only evaluates semantic similarity for the top-K base-scored jobs (default `50`).
- `SEMANTIC_MAX_BOOST` caps semantic contribution per job (default `5`).
- `SEMANTIC_MIN_SIMILARITY` minimum rounded similarity required for non-zero boost (default `0.72`).

Determinism contract:
- Text normalization is deterministic (`semantic_norm_v1`) before embedding/hash.
- Default backend is offline and deterministic (hash-based vectors, no network calls).
- Similarity is rounded to 6 decimals before threshold checks and boost math.
- Cache keys include `job_id`, `job_content_hash`, `candidate_profile_hash`, and `semantic_norm_v1`.
- Cache location: `state/embeddings/<model_id>/<cache_key>.json`.
- Cache entries store only model id, deterministic metadata, input hashes, and vector values.

Run artifact:
- Every run writes `state/runs/<run_id-sanitized>/semantic/semantic_summary.json` even when disabled.
- Every run writes `state/runs/<run_id-sanitized>/semantic/semantic_scores.json` (possibly empty when disabled).
- Short-circuit behavior:
  - `SEMANTIC_ENABLED=1` + `SEMANTIC_MODE=sidecar`: keep short-circuit when ranked outputs are fresh, and write semantic artifacts from existing ranked JSON.
  - `SEMANTIC_ENABLED=1` + `SEMANTIC_MODE=boost`: bypass short-circuit and rerun deterministic scoring so bounded boost can be applied.
- Summary includes:
  - `enabled`
  - `model_id`
  - `policy` (`mode`, `max_jobs`, `top_k`, `max_boost`, `min_similarity`)
  - `used_short_circuit`
  - `attempted_provider_profiles`
  - `cache_hit_counts`
  - `embedded_job_count`
  - `skipped_reason` (when disabled/unavailable/fail-closed)
- Scores artifact includes:
  - `job_id`
  - `base_score`
  - `similarity` (rounded, optional when not evaluated)
  - `semantic_boost`
  - `final_score`
  - `reasons` (for threshold/boost decisions)

Privacy boundary:
- Semantic artifacts do not store raw job description text.
- Only hashes, job ids, cache keys, and minimal provider/profile metadata are persisted.

Debug checklist:
- Confirm semantic config in env (`SEMANTIC_ENABLED`, `SEMANTIC_MODE`, `SEMANTIC_MODEL_ID`, `SEMANTIC_TOP_K`, `SEMANTIC_MAX_BOOST`, `SEMANTIC_MIN_SIMILARITY`).
- Inspect `state/runs/<run_id-sanitized>/semantic/semantic_summary.json` for `skipped_reason` and cache counters.
- Inspect `state/runs/<run_id-sanitized>/semantic/semantic_scores.json` for per-job similarity/boost decisions.
- Compare ranked output hashes with `SEMANTIC_ENABLED=0` or `SEMANTIC_MODE=sidecar` when validating no-rescore parity behavior.

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

Weekly insights inputs (deterministic):
- `state/runs/<run_id-sanitized>/ai/insights_input.<profile>.json`
- Built before weekly AI insights generation from deterministic artifacts only:
  - diffs (`new/changed/removed` counts + top titles)
  - 7-run rolling diff counts (`rolling_diff_counts_7`)
  - top families
  - score bucket distribution
  - deterministic top recurring skill tokens (`top_recurring_skill_tokens`)
  - median score trend delta (`median_score_trend_delta`)
- Prompt contract version: `weekly_insights_v3`.
- Cache key includes structured input hash + prompt version/hash (deterministic).
- No raw JD text is written into `insights_input.<profile>.json`; payload is summary-only.

## AI + Embedding Budget Guardrails

Deterministic per-run cost artifact:
- `state/runs/<run_id>/costs.json`
- fields:
  - `embeddings_count`
  - `embeddings_estimated_tokens`
  - `ai_calls`
  - `ai_estimated_tokens`
  - `total_estimated_tokens`

Guardrail env vars:
- `MAX_AI_TOKENS_PER_RUN` (default `0`, disabled)
- `MAX_EMBEDDINGS_PER_RUN` (default `0`, disabled)

Fail-closed behavior:
- If `ai_estimated_tokens > MAX_AI_TOKENS_PER_RUN`, run fails closed with validation-style exit code `2`.
- If `embeddings_count > MAX_EMBEDDINGS_PER_RUN`, run fails closed with validation-style exit code `2`.
- Failure is recorded in run report with `failed_stage=cost_guardrails`.

Notes:
- Estimation is deterministic and local only; no billing/provider APIs are called.
- AI model selection and temperature are unchanged by budget controls.

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
- Log retention summary:
  - `LOG_RETENTION enabled=<0|1> keep_runs=<N> runs_seen=<n> runs_kept=<n> log_dirs_pruned=<n> run_id=<run_id>`
  - retention is logs-only under `state/runs/<run_id>/logs/`; run artifacts are not deleted.

Inspect history identity/provenance artifacts:

```bash
cat state/history/<profile>/runs/<run_id>/identity_map.json
cat state/history/<profile>/runs/<run_id>/provenance.json
```

## Observability contract (lean)

Stdout remains canonical. Optional structured log sink can also write per-run JSONL logs:

```bash
python scripts/run_daily.py --profiles cs --log_file
# or
JOBINTEL_LOG_FILE=1 python scripts/run_daily.py --profiles cs
```

Per-run log pointers are written into `run_report.json` under `logs`.
The pointer contract is best-effort and cloud-agnostic:
- `logs.local`: local run/log paths plus optional structured JSONL sink path
- `logs.k8s`: kubectl command templates to locate pod/job logs by `JOBINTEL_RUN_ID`
- `logs.cloud`: CloudWatch group/stream (when env is set) plus a run-id filter pattern

Find logs by run_id locally:

```bash
run_id=<run_id>
safe_id=$(echo "$run_id" | tr -d ':-.')
cat "state/runs/$safe_id/run_report.json" | jq '.logs'
cat "state/runs/$safe_id/logs/run.log.jsonl"   # if log sink enabled
```

Find logs in k3s:

```bash
run_id=<run_id>
safe_id=$(echo "$run_id" | tr -d ':-.')
cat "state/runs/$safe_id/run_report.json" | jq '.logs.k8s'
kubectl -n jobintel get pods --sort-by=.metadata.creationTimestamp
kubectl -n jobintel get jobs --sort-by=.metadata.creationTimestamp
kubectl -n jobintel logs <pod-or-job> | rg "JOBINTEL_RUN_ID=$run_id"
```

Find logs in AWS (if `logs.cloud` pointers are populated in run report):

```bash
run_id=<run_id>
safe_id=$(echo "$run_id" | tr -d ':-.')
group=$(jq -r '.logs.cloud.cloudwatch_log_group // empty' "state/runs/$safe_id/run_report.json")
stream=$(jq -r '.logs.cloud.cloudwatch_log_stream // empty' "state/runs/$safe_id/run_report.json")
region=$(jq -r '.logs.cloud.region // empty' "state/runs/$safe_id/run_report.json")
pattern=$(jq -r '.logs.cloud.cloudwatch_filter_pattern // empty' "state/runs/$safe_id/run_report.json")
aws logs filter-log-events --region "$region" --log-group-name "$group" --filter-pattern "$pattern"
aws logs get-log-events --region "$region" --log-group-name "$group" --log-stream-name "$stream"
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

Developer fast loop: `make gate-fast` (pytest only).

Source-of-truth gate: `make gate-truth` (includes Docker no-cache).

Developer full gate: `make gate` (pytest + snapshot immutability + replay smoke).

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
