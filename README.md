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

GPT-5 is used for design, code generation, and refactoring.

A second model (e.g. Gemini) is used as a cross-model reviewer for critical modules (scraper, matching engine, etc.).

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
docker run --rm -v "$PWD/data:/app/data" --env-file .env jobintel:local scripts/run_ai_augment.py

# Scoring (reads AI-enriched input automatically when present; writes ranked outputs under ./data)
docker run --rm -v "$PWD/data:/app/data" --env-file .env jobintel:local scripts/score_jobs.py --profile cs --us_only
```

Compose convenience (also mounts ./data):

```bash
docker-compose up --build
```

Notes:
- Container is suitable for ECS/Fargate or cron on EC2; mount /app/data as a volume.
- No secrets are baked into the image; use env vars or task/env files.
- Snapshots under `data/openai_snapshots/` can be baked into the image; other data is excluded.

Canonical entrypoint:
- Use `scripts/run_daily.py` for the pipeline. Legacy runners (`run_full_pipeline.py`, `run_openai_pipeline.py`) are deprecated and exit non-zero with a message.

Verification snippet (stderr/stdout captured in logs; exit code propagated):
```bash
docker run --rm -v "$PWD/data:/app/data" jobintel:local --profiles cs --us_only --no_post ; echo exit=$?
```

## Runtime contract
- Volume: mount `./data` → `/app/data` (holds snapshots, cache, outputs).
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
docker run --rm -v "$PWD/data:/app/data" --env-file .env jobintel:local --profiles cs --us_only --no_post

# run with AI augment (ensures AI outputs are generated and scoring consumes them)
docker run --rm -v "$PWD/data:/app/data" --env-file .env jobintel:local --profiles cs --us_only --no_post --ai

# verify AI-enriched artifact is present before scoring
ls data/openai_enriched_jobs_ai.json
```
Run the last `ls` after the `--ai` invocation above to confirm `openai_enriched_jobs_ai.json` exists; the scoring step now picks it automatically when present.

## Roadmap

Sprint 0: Repo setup, models, and basic scraper skeleton

Sprint 1: Raw scraping of OpenAI careers → JSON

Sprint 2: Embeddings + basic classification

Sprint 3: Matching engine + Discord alerts

Sprint 4: Insights + Streamlit dashboard

Sprint 5: Add additional providers (Anthropic, etc.)