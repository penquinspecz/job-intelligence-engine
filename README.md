# Job Intelligence Engine (JIE)

[![CI](https://github.com/penquinspecz/job-intelligence-engine/actions/workflows/ci.yml/badge.svg)](https://github.com/penquinspecz/job-intelligence-engine/actions/workflows/ci.yml)
[![Docker Smoke](https://github.com/penquinspecz/job-intelligence-engine/actions/workflows/docker-smoke.yml/badge.svg)](https://github.com/penquinspecz/job-intelligence-engine/actions/workflows/docker-smoke.yml)
[![Lint](https://github.com/penquinspecz/job-intelligence-engine/actions/workflows/lint.yml/badge.svg)](https://github.com/penquinspecz/job-intelligence-engine/actions/workflows/lint.yml)

An AI-powered job intelligence system that monitors frontier AI company careers pages, classifies roles, matches them to a candidate profile, and generates deterministic artifacts, diffs, and alerts.

This repo is built as a **portfolio-grade, production-minded system**: deterministic by default, debuggable via artifacts, and deployable as a scheduled job (AWS/ECS or Kubernetes CronJob). The “AI” is intentionally **last-mile**: the deterministic pipeline produces stable outputs first; AI (when enabled) reads those artifacts under strict guardrails.

---

## Status

Active development with strong determinism guardrails:
- One canonical pipeline entrypoint: `scripts/run_daily.py`
- Offline snapshot mode supported (CI + K8s guardrails)
- Run registry + artifact persistence under `state/runs/<run_id>/`
- Diff artifacts + optional diff-only Discord notifications

Roadmap lives in `docs/ROADMAP.md`.

---

## Goals

- Continuously scrape careers pages for frontier AI companies (starting with OpenAI; designed to expand safely).
- Classify roles by function (Solutions Architecture, AI Deployment, Customer Success, etc.).
- Compute a fit score and gap analysis against a structured candidate profile.
- Produce deterministic run artifacts and a “changes since last run” diff report.
- Generate weekly hiring trend summaries and bounded alerts for high-fit roles.
- Demonstrate practical, safe use of LLMs/AI in a **guardrailed, reproducible pipeline**.
- Serve as a long-lived portfolio artifact: deployable, test-backed, and explainable.

_(Added, not replacing prior intent)_:
- Target roles include technical Customer Success / Solutions Architecture / Technical Success / Deployment-facing roles.
- Optimize for CNCF-ish operational discipline: container-first, K8s-native patterns, predictable logs/artifacts, and boring repeatability.

---

## Architecture

High level:

- Provider layer (snapshot-first; live mode optional and bounded)
- Deterministic extraction + classification pipeline
- Matching engine (fit + gaps) producing ranked artifacts per profile
- Run registry + run report (hashes, inputs, outputs, timings)
- Diff report (identity-based, stable ordering) + optional Discord alerts
- Minimal dashboard API (FastAPI) to browse runs and artifacts (API-first; UI can come later)
- Ops layer (AWS ECS scheduled runs / K8s CronJob & run-once Job) with runbooks and verification steps

---

## AI-Assisted Development

This project is intentionally built using AI pair programming:

- GPT-5 is used for design, project management, and daily task guidance.
- A second model (e.g., Gemini) is used as a cross-model reviewer for critical modules (provider logic, determinism contract, identity/diff logic).
- Implementation work is executed via an agent workflow (e.g., Codex/Cursor), with emphasis on:
  - small, test-backed diffs
  - deterministic outputs
  - explicit exit code contracts
  - “truth gates” (Docker build with tests)

_(Added, not replacing prior intent)_:
- Multi-model development is a **safety technique**: independent review reduces blind spots and helps catch subtle contract violations.
- The goal is not “vibe coding”; it is **repeatable engineering** with verifiable artifacts and minimal churn.

---

## Install (canonical)

```bash
python -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e .
pip install ".[dev]"        # contributors
pip install ".[dashboard]"  # dashboard runtime
pip install ".[snapshots]"  # Playwright snapshots

pyproject.toml is the canonical source of dependencies. requirements.txt is the Docker/CI export.

Example run (no Discord post):

python scripts/run_daily.py --profiles cs --us_only --no_post


⸻

Local quickstart

After creating the venv above, you can run the common stages via make:

make test
make enrich
make score            # default PROFILE=cs
make all              # test + enrich + score


⸻

Canonical entrypoint + run outputs

Entrypoint: scripts/run_daily.py

Runs produce artifacts under:
	•	state/runs/<run_id>/... (run registry + artifacts + reports)
	•	data/... (inputs/snapshots/outputs; depending on mode)

Exit code contract:
	•	0 success
	•	2 validation / missing inputs / deterministic “not runnable”
	•	>=3 runtime/provider failures

⸻

Docker (AWS-ready)

Build and run locally (expects ./data and ./state mounted):

docker build -t jobintel:local .
docker run --rm \
  -v "$PWD/data:/app/data" \
  -v "$PWD/state:/app/state" \
  --env-file .env \
  jobintel:local --profiles cs --us_only --no_post

Run with AI augmentation (guardrailed; opt-in):

docker run --rm \
  -v "$PWD/data:/app/data" \
  -v "$PWD/state:/app/state" \
  --env-file .env \
  jobintel:local --profiles cs --us_only --no_post --ai


⸻

Determinism & goldens
	•	Snapshots under data/*_snapshots/ are pinned fixtures; do not mutate them during tests.
	•	Golden tests assert deterministic transforms over pinned snapshots, not upstream job volatility.
	•	Snapshot bytes are guarded by tests/fixtures/golden/snapshot_bytes.manifest.json.
	•	Verify locally: python scripts/verify_snapshots_immutable.py
	•	Docker (no-cache) is the source of truth for CI parity:

DOCKER_BUILDKIT=1 docker build --no-cache --build-arg RUN_TESTS=1 -t jobintel:tests .

Determinism contract: docs/DETERMINISM_CONTRACT.md

⸻

CI / local truth gates

Fast local gate (matches PR expectations without requiring AWS secrets):

make gate-fast

CI-equivalent Docker truth gate:

DOCKER_BUILDKIT=1 docker build --no-cache --build-arg RUN_TESTS=1 -t jobintel:tests .


⸻

Kubernetes ops (CronJob + run-once)

K8s manifests + runbooks live under ops/k8s/.
	•	CronJob is intended for scheduled, deterministic runs (offline-safe where required by contract).
	•	A run-once Job exists for ad-hoc parity runs and debugging.

See: ops/k8s/README.md

⸻

AWS ops (ECS scheduled run + S3 publish)

AWS runbooks and templates live under ops/aws/ and associated docs.

Milestone proof-run artifacts and verification checklist are documented (when enabled in your branch):
	•	CloudWatch log line showing run_id
	•	S3 objects under runs/<run_id>/... and latest/...
	•	Offline verification via publish plan + verifier script

See roadmap + runbooks under docs/.

⸻

Troubleshooting

Common issues:
	•	CI “ji_engine not found”: ensure CI installs the package (pip install -e .) before running scripts.
	•	Ruff format/lint failures: run python -m ruff check --fix . and python -m ruff format ..
	•	Docker “no space left on device”: prune Docker build cache:
	•	docker builder prune -af
	•	docker system prune -af --volumes (more aggressive)

⸻

License

TBD.
