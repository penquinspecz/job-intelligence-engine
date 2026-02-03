# Job Intelligence Engine (JIE)

[![CI](https://github.com/penquinspecz/job-intelligence-engine/actions/workflows/ci.yml/badge.svg)](https://github.com/penquinspecz/job-intelligence-engine/actions/workflows/ci.yml)
[![Docker Smoke](https://github.com/penquinspecz/job-intelligence-engine/actions/workflows/docker-smoke.yml/badge.svg)](https://github.com/penquinspecz/job-intelligence-engine/actions/workflows/docker-smoke.yml)
[![Lint](https://github.com/penquinspecz/job-intelligence-engine/actions/workflows/lint.yml/badge.svg)](https://github.com/penquinspecz/job-intelligence-engine/actions/workflows/lint.yml)

An AI-powered job intelligence system that monitors frontier AI company careers pages, classifies roles, matches them to a candidate profile, and generates deterministic artifacts, diffs, and alerts.

This repository is built as a **portfolio-grade, production-minded system**: deterministic by default, debuggable via artifacts, and deployable as a scheduled job (AWS/ECS or Kubernetes CronJob).  
The “AI” is intentionally **last-mile** — the deterministic pipeline produces stable outputs first; AI (when enabled) reads those artifacts under strict guardrails.

---

## Status

**Active development** with strong determinism guardrails:

- **Canonical pipeline entrypoint:** `scripts/run_daily.py`
- **Offline snapshot mode:** supported (CI + Kubernetes guardrails)
- **Run registry & artifact persistence:** `state/runs/<run_id>/`
- **Diff artifacts:** identity-based diffs with optional diff-only Discord notifications

**Roadmap:** `docs/ROADMAP.md`

---

## Goals

- **Continuously monitor** careers pages for frontier AI companies  
  (starting with OpenAI; designed to expand safely).
- **Classify roles** by function (Solutions Architecture, AI Deployment, Customer Success, etc.).
- **Compute fit scores and gap analysis** against a structured candidate profile.
- **Produce deterministic run artifacts** and “changes since last run” diff reports.
- **Generate bounded alerts and summaries** (e.g., weekly hiring trends, high-fit role alerts).
- **Demonstrate safe, practical AI usage** in a guardrailed, reproducible pipeline.
- **Serve as a long-lived portfolio artifact:** deployable, test-backed, explainable.

**Added (not replacing prior intent):**
- Target roles include **Technical Customer Success**, **Solutions Architecture**, **Technical Success**, and other deployment-facing roles.
- Optimize for **CNCF-style operational discipline**: container-first design, Kubernetes-native execution, predictable logs and artifacts, and boring repeatability.

---

## Architecture

**High-level design:**

- **Provider layer:** snapshot-first; live mode optional and bounded
- **Pipeline:** deterministic extraction and classification
- **Matching engine:** fit and gap analysis producing ranked artifacts per profile
- **Run report:** hashes, inputs, outputs, timings
- **Diff report:** identity-based, stable ordering with optional notifications
- **Dashboard API:** minimal FastAPI service to browse runs and artifacts (API-first)
- **Ops layer:** AWS ECS scheduled runs or Kubernetes CronJob, plus run-once Jobs with runbooks and verification steps

---

## AI-Assisted Development

This project is intentionally built using AI pair programming:

- **GPT-5** is used for design, project management, and daily task guidance.
- **A second model** (e.g., Gemini) is used as a cross-model reviewer for critical components  
  (provider logic, determinism contracts, identity and diff logic).
- **Implementation is executed via an agent workflow** (e.g., Codex or Cursor), emphasizing:
  - small, test-backed diffs
  - deterministic outputs
  - explicit exit code contracts
  - “truth gates” (Docker builds with tests)

**Added (not replacing prior intent):**
- Multi-model development is treated as a **safety technique**: independent review reduces blind spots and catches subtle contract violations.
- The goal is not “vibe coding”; it is **repeatable engineering** with verifiable artifacts and minimal churn.

---

## Install

### Canonical

```bash
python -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e .
pip install ".[dev]"        # contributors
pip install ".[dashboard]"  # dashboard runtime
pip install ".[snapshots]"  # Playwright snapshots
    **Canonical dependency source:** `pyproject.toml`  
    **Docker / CI export:** `requirements.txt`

    ## Example run (no Discord post)

        python scripts/run_daily.py --profiles cs --us_only --no_post

    ---

    ## Local Quickstart

    After creating the virtual environment above, run common stages via `make`:

        make test
        make enrich
        make score            # default PROFILE=cs
        make all              # test + enrich + score

    ---

    ## Canonical Entrypoint & Run Outputs

    **Entrypoint:** `scripts/run_daily.py`

    **Runs produce artifacts under:**
    - `state/runs/<run_id>/` — run registry, artifacts, and reports
    - `data/` — inputs, snapshots, and outputs (depending on mode)

    **Exit code contract:**
    - `0` — success
    - `2` — validation failure, missing inputs, or deterministic “not runnable”
    - `>=3` — runtime or provider failures

    ---

    ## Docker (AWS-ready)

    ### Build and run locally

    Expects `./data` and `./state` to be mounted:

        docker build -t jobintel:local .
        docker run --rm \
          -v "$PWD/data:/app/data" \
          -v "$PWD/state:/app/state" \
          --env-file .env \
          jobintel:local --profiles cs --us_only --no_post

    ### Run with AI augmentation (guardrailed; opt-in)

        docker run --rm \
          -v "$PWD/data:/app/data" \
          -v "$PWD/state:/app/state" \
          --env-file .env \
          jobintel:local --profiles cs --us_only --no_post --ai

    ---

    ## Determinism & Goldens

    - Snapshots under `data/*_snapshots/` are pinned fixtures; do not mutate them during tests.
    - Golden tests assert deterministic transforms over pinned snapshots, not upstream job volatility.
    - Snapshot bytes are guarded by `tests/fixtures/golden/snapshot_bytes.manifest.json`.
    - Verify locally:

        python scripts/verify_snapshots_immutable.py

    - Docker (no-cache) is the CI parity source of truth:

        DOCKER_BUILDKIT=1 docker build --no-cache --build-arg RUN_TESTS=1 -t jobintel:tests .

    **Determinism contract:** `docs/DETERMINISM_CONTRACT.md`

    ---

    ## CI / Local Truth Gates

    Fast local gate (matches PR expectations without AWS secrets):

        make gate-fast

    CI-equivalent Docker truth gate:

        DOCKER_BUILDKIT=1 docker build --no-cache --build-arg RUN_TESTS=1 -t jobintel:tests .

    ---

    ## Kubernetes Ops (CronJob + run-once)

    K8s manifests and runbooks live under `ops/k8s/`.

    - CronJob is intended for scheduled, deterministic runs (offline-safe where required).
    - A run-once Job exists for ad-hoc parity runs and debugging.

    See: `ops/k8s/README.md`

    ---

    ## AWS Ops (ECS scheduled run + S3 publish)

    AWS runbooks and templates live under `ops/aws/`.

    Milestone proof-run artifacts and verification checklist:
    - CloudWatch log line showing `run_id`
    - S3 objects under `runs/<run_id>/` and `latest/`
    - Offline verification via publish plan + verifier script

    See roadmap and runbooks under `docs/`.

    ---

    ## Troubleshooting

    - CI “ji_engine not found”: ensure CI installs the package (`pip install -e .`)
    - Ruff failures:

        python -m ruff check --fix .
        python -m ruff format .

    - Docker “no space left on device”:

        docker builder prune -af
        docker system prune -af --volumes

    ---

    ## License

    TBD.