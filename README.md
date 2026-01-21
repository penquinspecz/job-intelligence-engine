# Job Intelligence Engine (JIE)

An AI-powered job intelligence system that monitors frontier AI company careers pages, classifies roles, matches them to a candidate profile, and generates insights and alerts.

## Status

Early development. Architecture and project plan in progress.

## Goals

- Continuously scrape OpenAI careers (later: Anthropic, Google, etc.)
- Classify roles by function (Solutions Architecture, AI Deployment, CS, etc.)
- Compute a fit score and gap analysis against a structured candidate profile
- Generate weekly hiring trend summaries and real-time alerts for high-fit roles
- Demonstrate practical use of LLMs, embeddings, and workflow automation

## Architecture

High level:

- Provider-agnostic scraper layer  
- Embedding + classification pipeline (OpenAI API)  
- Matching engine (fit + gaps)  
- Insight generator (weekly / monthly pulse)  
- Notification & dashboard layer  

## AI-Assisted Development

This project is intentionally built using AI pair programming:

GPT-5 is used for design and project management, as well as daily task guidance.

A second model (e.g. Gemini) is used as a cross-model reviewer for critical modules (scraper, matching engine, etc.).

Development is done in Codex IDE using a variety of models depending on the task.

The goal is to demonstrate practical, safe use of multi-model workflows for software engineering.

## Local setup (editable install)

```bash
python -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e .
# Example run (no Discord post):
python scripts/run_daily.py --profiles cs --us_only --no_post
```

## Local quickstart

After creating the venv above, you can run the common stages via `make`:

```bash
make test
make enrich
make score            # default PROFILE=cs
make all              # test + enrich + score
```

## Docker (AWS-ready)

Build and run locally (expects ./data mounted to /app/data):

```bash
docker build -t jobintel:local .
docker run --rm -v "$PWD/data:/app/data" --env-file .env jobintel:local \
  # defaults: --profiles cs --us_only --no_post

# override defaults as needed:
docker run --rm -v "$PWD/data:/app/data" --env-file .env jobintel:local \
  --profiles cs,tam,se --us_only --no_post

# run with AI augment stage
docker run --rm -v "$PWD/data:/app/data" --env-file .env jobintel:local \
  --profiles cs --us_only --no_post --ai
```

## Docker quickstart

The image runs tests during `docker build`, and the container `ENTRYPOINT` is `python`, so you can run any script directly.

```bash
docker build -t jobintel:local .

# AI augment (writes data/openai_enriched_jobs_ai.json into the mounted ./data volume)
docker run --rm -v "$PWD/data:/app/data" -v "$PWD/state:/app/state" --env-file .env jobintel:local --profiles cs --us_only --no_post --ai

# Scoring (reads AI-enriched input automatically when present; writes ranked outputs under ./data)
docker run --rm -v "$PWD/data:/app/data" -v "$PWD/state:/app/state" --env-file .env jobintel:local --profile cs --us_only --no_post
```

Compose convenience (also mounts ./data):

```bash
docker-compose up --build
```

## Debugging the container

You can override the default `ENTRYPOINT` to run a quick Python snippet or drop into a shell:

```bash
docker run --rm -v "$PWD/data:/app/data" --entrypoint python jobintel:local -c "import sys; print(sys.executable)"
docker run --rm -it -v "$PWD/data:/app/data" --entrypoint sh jobintel:local
```

Notes:
- Container is suitable for ECS/Fargate or cron on EC2; mount /app/data as a volume.
- No secrets are baked into the image; use env vars or task/env files.
- Snapshots under `data/openai_snapshots/` can be baked into the image; other data is excluded.

## Updating provider snapshots

Use the CLI snapshot refresh to fetch and validate HTML before overwriting snapshots.

```bash
# Refresh OpenAI snapshot with defaults
.venv/bin/python -m src.jobintel.cli snapshots refresh --provider openai

# Refresh all known providers (from config/providers.json)
.venv/bin/python -m src.jobintel.cli snapshots refresh --provider all

# Use Playwright for snapshot fetch
.venv/bin/python -m src.jobintel.cli snapshots refresh --provider openai --fetch playwright

# Use Playwright via env
JOBINTEL_SNAPSHOT_FETCH=playwright .venv/bin/python -m src.jobintel.cli snapshots refresh --provider openai

# Refresh snapshots, then run offline
.venv/bin/python -m src.jobintel.cli snapshots refresh --provider openai
.venv/bin/python -m src.jobintel.cli run --offline --role cs --providers openai --no_post --no_enrich
```

## Snapshot validation

Validate committed snapshots before running offline/CI:

```bash
.venv/bin/python -m src.jobintel.cli snapshots validate --all
.venv/bin/python -m src.jobintel.cli snapshots validate --provider openai --data-dir ci_data
```

Legacy option (stdlib `urllib`):

```bash
.venv/bin/python scripts/update_snapshots.py --provider openai
```

Canonical entrypoint:
- Use `scripts/run_daily.py` for the pipeline. Legacy runners (`run_full_pipeline.py`, `run_openai_pipeline.py`) are deprecated and exit non-zero with a message.

Verification snippet (stderr/stdout captured in logs; exit code propagated):
```bash
docker run --rm -v "$PWD/data:/app/data" jobintel:local --profiles cs --us_only --no_post ; echo exit=$?
```

## Runtime contract
- Runs as non-root user `app` by default; artifacts on mounted volumes remain host-writable (no sudo/chmod needed after runs).
- Volumes:
  - `./data` → `/app/data` (snapshots, cache, outputs)
  - `./state` → `/app/state` (history, metadata, user_state)
- Run report schema version is recorded in run metadata as `run_report_schema_version`.
- Env vars:
  - `DISCORD_WEBHOOK_URL` (optional; if unset, alerts are skipped)
  - `CAREERS_MODE` (optional; defaults to AUTO)
  - `JOBINTEL_S3_BUCKET` (optional) + `JOBINTEL_S3_PREFIX` (optional): when set, AI cache and embedding cache use S3; defaults remain filesystem.
  - Any profile/flag overrides via CLI args to `scripts/run_daily.py`.
- Example ECS/Fargate usage (high-level):
  - Build/push image.
  - Task definition: command `python scripts/run_daily.py --profiles cs,tam,se --us_only --no_post`; mount EFS/S3-backed volume to `/app/data`; supply env (e.g., webhook) via task env/Secrets Manager.
  - Schedule via EventBridge to trigger the task on your cadence.
Docker run cheatsheet:
```bash
# build the image
docker build -t jobintel:local .

# default run (no AI augment, no Discord)
docker run --rm \
  -v "$PWD/data:/app/data" \
  -v "$PWD/state:/app/state" \
  --env-file .env jobintel:local --profiles cs --us_only --no_post

# run with AI augment (ensures AI outputs are generated and scoring consumes them)
docker run --rm \
  -v "$PWD/data:/app/data" \
  -v "$PWD/state:/app/state" \
  --env-file .env jobintel:local --profiles cs --us_only --no_post --ai

# verify AI-enriched artifact is present before scoring
ls data/openai_enriched_jobs_ai.json
```
Run the last `ls` after the `--ai` invocation above to confirm `openai_enriched_jobs_ai.json` exists; the scoring step now picks it automatically when present.

Mounting `/app/state` alongside `/app/data` keeps `state/history` persisted between runs; otherwise history disappears when the container exits.

```bash
# after a run
# (e.g., state/history/2026-01-01/20260101T000000Z/cs/run_summary.txt)
find state -maxdepth 10 -type f
```

## Local Docker smoke

Run the same containerized smoke flow as CI (offline, baked snapshots/state):

```bash
make smoke
./scripts/smoke_docker.sh
```

Skip the image build (reuse existing `jobintel:local`):

```bash
make smoke-fast
./scripts/smoke_docker.sh --skip-build
```

Multi-provider smoke (bounded profiles):

```bash
./scripts/smoke_docker.sh --providers openai,anthropic --profiles cs
```

Override defaults with env vars:

```bash
CONTAINER_NAME=jobintel_smoke_alt ./scripts/smoke_docker.sh
ARTIFACT_DIR=smoke_out ./scripts/smoke_docker.sh
SMOKE_SKIP_BUILD=1 ./scripts/smoke_docker.sh
```

## Smoke contract

The smoke contract check validates deterministic properties of smoke artifacts so CI stays stable:
- `openai_labeled_jobs.json` exists and is non-empty
- `openai_ranked_jobs.cs.json` has at least N items (default 5)
- `openai_ranked_jobs.cs.csv` row count matches ranked JSON
- `run_report.json` includes provider=openai, scrape_mode=SNAPSHOT, and classified_job_count matches labeled length

To adjust thresholds intentionally, pass a new minimum:

```bash
python3 scripts/smoke_contract_check.py smoke_artifacts --min-ranked 10
```

## Delta summary

Each run report includes a `delta_summary` section with per-provider/profile deltas between the current run and the latest available baseline. When no baseline is available, `baseline_run_id` and `baseline_run_path` are null and all delta counts are zero (unchanged is zero).

## Dev commands

```bash
.venv/bin/pip install -e .
.venv/bin/python -m pytest -q
.venv/bin/ruff check .
```

## Quick commands

```bash
make test
make lint
make docker-build
make docker-run-local
make report
```

`make report` runs `scripts.report_changes` inside the Docker image (mounting `state/`, overriding entrypoint) to compare the latest CS run; override `PROFILE`/`LIMIT` as needed.

## Uploading run history to S3

```
docker run --rm \
  -v "$PWD/data:/app/data" \
  --env-file .env \
  jobintel:local \
  python scripts/publish_s3.py \
  --bucket my-bucket \
  --profile cs \
  --latest \
  --dry_run
```

Set `--run_id` instead of `--latest` to upload a specific run, and omit `--dry_run` to perform the actual upload.

Note: `publish_s3.py` only uploads artifacts under `state/history/**`; other state files (embed cache, etc.) are ignored.

## AWS deployment templates

- Use `ops/aws/ecs-taskdef.json` as the basis for a Fargate task that mounts `/app/data` & `/app/state`, sets the JOBINTEL_ vars, and runs `python scripts/run_daily.py --profiles cs --us_only --no_enrich`.
- Trigger it with `ops/aws/eventbridge-rule.json` on a cron schedule.
- After each run, schedule a second job (or step) that runs `python scripts/publish_s3.py --profile cs --latest --bucket ...` to upload the persisted history to S3.


## Roadmap

### Phase 0 — Local & CI reliability
- [x] Deterministic ranking tie-breakers
- [x] CI-safe `--no_enrich` + changelog diff output
- [x] Structured logging + failure alerts (stderr/stdout tails)
- [x] Absolute paths, `ensure_dirs()`, and atomic writes (data/state/snapshot/cache)
- [x] GraphQL null jobPosting guard + golden master scoring test
- [x] BeautifulSoup HTML-to-text for deterministic enrichment
- [ ] Broader failure surfacing (Ashby retries / explicit unavailable on 4xx/5xx)
- [ ] Log rotation / destination strategy (launchd/stdout)

### Phase 1 — Packaging & deployment
- [x] Docker image that runs `pytest` during build and respects `/app/data`
- [x] Single canonical entrypoint (`scripts/run_daily.py`) with deterministic scripts
- [x] Debugging container docs + quickstart guidance
- [ ] Full pipeline golden master (snapshot HTML → ranked outputs)
- [ ] Cleanup legacy scripts (`run_full_pipeline`, `run_openai_pipeline`) and move integrations fully under `src/ji_engine`
- [ ] Logging destination/rotation (launchd docs, log sink)

### Phase 2 — State, history & intelligence
- [x] Persist ranked artifacts, shortlist, and fingerprints per profile
- [x] “Changes since last run” shortlist section + changelog logs
- [x] Alert gating (skip Discord when diffs are empty)
- [ ] Job fingerprinting per `job_identity()` (title/location, URLs, description hash)
- [ ] Additional providers (Anthropic, other APIs) with snapshot/live toggles
- [ ] Smarter scoring blends / AI-assisted insights
- [ ] Dashboard/alerts enhancements (structured payloads, filters)

### Phase 3 — Packaging, ops & monitoring
- [ ] Config validation + clear exit codes
- [ ] Structured logs + run metadata (timings, counts, hashes)
- [ ] S3-backed caches for AI output/embeddings (optional backend) + OBS telemetry
- [ ] Observability/alerting (CloudWatch, alarms, runbooks)

### Phase 4 — Hardening & scaling
- [ ] Rate limiting / backoff for providers
- [ ] Provider abstraction for multiple job boards
- [ ] Cost controls (limits, caching, sampling)
- [ ] Optional DynamoDB or similar index for job state/history
