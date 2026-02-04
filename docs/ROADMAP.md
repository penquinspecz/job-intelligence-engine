# JobIntel Roadmap

This roadmap is the anti-chaos anchor. We optimize for:
1) deterministic outputs, 2) debuggability, 3) deployability, 4) incremental intelligence.
If a change doesn’t advance a milestone’s Definition of Done (DoD), it’s probably churn.

---

## Principles / Guardrails

- **One canonical pipeline entrypoint:** `scripts/run_daily.py`
- **Determinism over cleverness:** same inputs → same outputs
- **Explicit input selection rules:** labeled vs enriched vs AI-enriched must be predictable
- **Small, test-backed changes:** no “refactor weeks” unless it buys a milestone
- **Operational truth lives in artifacts:** run metadata + logs + outputs > vibes
- **LLMs are allowed only with guardrails:** cache + schema + fail-closed + reproducible settings
- **AI is last-mile:** deterministic pipeline produces stable artifacts; AI reads them and produces insight outputs.
- **Multi-candidate is Phase 2+:** design plumbing now (paths/schemas), do not build UI complexity until Phase 1 is boring.
- **Tests must be deterministic regardless of optional deps:** unit tests cannot change behavior based on whether optional tooling (e.g., Playwright) is installed
- **Single source of truth for dependencies:** Docker, CI, and local dev install from the same dependency contract (no “works in Docker only” drift)
- **Docs are a contract:** README status/architecture must match the runnable system; no “early dev” drift when the system is operational
- **Cloud is not special:** AWS runs must be as replayable and inspectable as local runs (S3 is the artifact source of truth)

---

## Updated Product Intent (so we don’t accidentally build the wrong thing)

### Phase 1 (current focus): “Useful every day, deployable via Kubernetes or cloud-agnostic schedulers”
- Daily run produces artifacts + run registry
- Discord notifications (deltas + top items)
- Minimal dashboard API to browse runs/artifacts
- Simple weekly AI insights report (cached, guarded, post summary to Discord)
- Kubernetes CronJob deployment: scheduled runs + object-store publishing + domain-backed dashboard endpoint (AWS optional)

### Phase 2+: “Multi-user + powerful UI + deeper AI”
- Users upload resume/job profile → their own scoring runs, alerts, and state
- UI (simple but powerful): filters, search, explainability per job, lifecycle actions
- AI: profile-aware coaching + per-job insights/recommendations + outreach suggestions (still guardrailed/cached)

---

## Current State (as of this commit)

### Completed foundation (verified in repo/tests)
- [x] Deterministic ranking + tie-breakers
- [x] `--prefer_ai` is opt-in; no implicit AI switching
- [x] Short-circuit reruns scoring if ranked artifacts missing
- [x] `--no_enrich` input selection guarded by freshness (prefer enriched only when newer)
- [x] Strong regression coverage across scoring paths + short-circuit behavior
- [x] Docker smoke run validated; snapshots baked correctly (including per-job HTML)
- [x] Repo-root path safety: config no longer depends on CWD (`REPO_ROOT` anchored to `__file__`)
- [x] Run metadata includes inputs + scoring inputs by profile + output hashes
- [x] Run report schema version is written and asserted in tests
- [x] Exit codes normalized to policy: `0` success, `2` validation/missing inputs, `>=3` runtime/provider failures
- [x] Job identity URLs normalized (query/fragment stripped; stable casing/trailing slash)
- [x] `SMOKE_SKIP_BUILD` override works; snapshot debugging helpers exist (`make debug-snapshots`)
- [x] Scoring diagnostics (min/p50/p90/max + bucket counts + top 10) printed in logs
- [x] Top-N markdown output generated per run (even if shortlist is empty)
- [x] `--min_score` + `SMOKE_MIN_SCORE` plumbing added (back-compat alias preserved)
- [x] CS scoring heuristics recalibrated (shortlist no longer empty at sensible thresholds)
- [x] Score clamping to 0–100 to prevent runaway (distribution tuning is iterative)

### Delivery layer now implemented (Phase 1 progress)
- [x] **Discord run-summary alerts** (no-op when webhook unset; honors `--no_post`; offline-safe)
- [x] **Run registry + artifact persistence** under `state/runs/<run_id>/`
- [x] **Minimal FastAPI dashboard API**:
  - `/healthz`, `/runs`, `/runs/{run_id}`, `/runs/{run_id}/artifact/{name}`
  - Serves artifacts with correct content types
- [x] **Weekly AI insights step (guardrailed, cached)**:
  - Prompt template versioned
  - Output MD/JSON saved into run dir
  - Posts short Discord summary when enabled
  - Opt-in via `AI_ENABLED=1`; stub output when disabled/unavailable

### New conventions added (scaffold + partial integration)
- [x] `state/user_state/` convention + loader utility returning `{}` if missing (scaffold)
- [x] User state overlay annotated in outputs (status tags/notes)
- [ ] User state overlay influences filtering/alert semantics (Milestone 3 work item)

---

## Known Sharp Edges / TODO (updated)
- [x] **Replayability gap closed:** selected scoring inputs are archived per run for regeneration
- [x] Provider failure surfacing: retries/backoff, explicit unavailable reasons in run report + Discord
- [ ] Log destination / rotation strategy for AWS runs (stdout + CloudWatch + retention)
- [x] “Replay a run” workflow exists (`scripts/replay_run.py`) with hash verification + optional `--recalc`
- [ ] Dashboard dependency management (FastAPI/uvicorn must be installable in offline/CI contexts or tests should run in CI image)
- [ ] AI insights scope: currently weekly “pulse”; Phase 2 adds per-job recommendations and profile-aware coaching.
- [ ] Document CI smoke gate design and failure modes (why it fails, what to inspect)
- [x] **IAM footguns:** document runtime vs operator verify roles for object-store access in K8s (IRSA) + AWS
- [ ] **Artifact hygiene:** ensure secrets never leak into run reports/artifacts; add a redaction sanity test if needed

---

## Milestone 1 — Daily run is deterministic & debuggable (Local + Docker + CI)

**Goal:** “Boring daily.” If something changes, we know *exactly* why.

### Definition of Done (DoD)
- [x] `pytest -q` passes locally and in CI
- [x] Docker smoke run produces ranked outputs for at least one profile
- [x] A single JSON run report is written every run (counts, hashes, selected inputs, output hashes)
- [x] Clear exit codes: `0` success, `2` validation/missing inputs, `>=3` runtime/provider failures
- [x] Docs: “How to run / How to debug / What files to inspect”
- [x] Snapshot debugging helpers exist (`make debug-snapshots`)
- [x] Scoring diagnostics present in logs
- [x] CI smoke test is deterministic and artifact-validated (no heredoc or shell fragility)
- [x] CI, Docker, and local execution verified against identical dependency contracts

### Work Items
- [x] `docs/OPERATIONS.md` describing input selection rules + flags + failure modes + artifact locations
- [x] Run report includes: run_id, git_sha/image_tag (best-effort), timings, counts per stage,
      selected input paths + mtimes + hashes, output hashes
- [x] CI docker smoke test asserts ranked artifacts + run report exists
- [x] Baked-in snapshot validation (index + per-job HTML count check)

---

## Milestone 1.5 — Determinism Contract & Replayability (Local Truth > Vibes)

**Goal:** Given a run report, you can reproduce and explain the output.

### Definition of Done (DoD)
- [x] Run report records *why* each scoring input was selected (rule + freshness comparison),
      not just which file was used.
- [x] Run report has a stable schema contract documented:
  - [x] `run_report_schema_version` exists
  - [x] `docs/RUN_REPORT.md` documents fields + meanings
- [x] **Input archival exists for regeneration:** the *exact selected scoring inputs* for a run are copied into
      `state/runs/<run_id>/inputs/...` (or equivalent), sufficient to re-run scoring without mutable `data/` files.
- [x] “Replay a run” instructions exist:
  - given a run_id (and/or archived history dir), reproduce the exact shortlist output
- [x] Optional helper script `scripts/replay_run.py` validates hashes and prints a clear reproducibility report.
- [x] Optional but high-leverage: replay tool can **recalculate** scoring from archived inputs and diff against archived outputs.

### Work Items
- [x] Add `selection_reason` fields in run report for:
  - labeled vs enriched resolution
  - enriched vs AI-enriched resolution (when applicable)
- [x] Add `docs/RUN_REPORT.md` with schema and troubleshooting
- [x] Add `scripts/replay_run.py` (read-only) + tests
- [x] Add input archival step to end-of-run:
  - archive the *selected* scoring inputs (labeled/enriched/ai-enriched, whichever won)
  - archive the candidate profile used for scoring
  - record archived paths + hashes in run report
- [x] Extend replay tooling with `--recalc` (or similar):
  - load archived inputs
  - run current scoring against them deterministically
  - diff outputs vs archived ranked artifacts

---

## Milestone 2 — Scheduled run + object-store publishing (Kubernetes CronJob first)

**Goal:** “It runs itself.” A Kubernetes CronJob (or equivalent orchestrator) runs daily, publishes to an
S3-compatible object store, optional alerts.

### Definition of Done (DoD)
- [ ] Kubernetes CronJob runs end-to-end with mounted/ephemeral state
- [x] Publish plan + offline verification contract exists for object-store keys (verifiable allowlist)
- [ ] End-to-end publish to a real object-store bucket verified (runs + latest keys)
- [x] Discord alerts sent only when diffs exist (or optionally always send summary; configurable)
- [x] Minimal object-store IAM policy documented (least privilege; AWS example)
- [ ] Domain-backed dashboard endpoint (API first; UI can come later)
- [ ] Runbook: deploy, inspect last run, roll back, rotate secrets
 - [ ] Proof artifacts captured (for verification):
   - CloudWatch log line with `run_id`
   - `s3://<bucket>/<prefix>/runs/<run_id>/<provider>/<profile>/...` populated
   - `python scripts/verify_published_s3.py --bucket <bucket> --run-id <run_id> --verify-latest` outputs OK

### Work Items
- [x] Implement `scripts/publish_s3.py` and wire it into end-of-run (after artifacts persisted)
- [x] Publish plan + offline verification (`publish_s3 --plan --json`, `verify_published_s3 --offline`)
- [x] Orchestrator-shape local smoke (`make ecs-shape-smoke`)
- [x] K8s CronJob manifests exist (base + AWS overlay)
- [x] K8s overlays for live/publish modes exist (composable)
- [x] Proof tooling exists (`scripts/prove_cloud_run.py`)
- [x] Machine-parseable run_id log line + success pointer exists
- [x] IRSA wiring is parameterized and documented (no manual YAML editing)
- [x] Deterministic helper exists to discover subnet_ids for EKS bootstrap
- [ ] Proof run executed (EKS one-off job + real S3 publish + proof JSON captured)
- [ ] EKS bootstrap path exists (Terraform) + IRSA wiring documented
- [ ] EKS can pull image (ECR golden path documented + working)
- Receipts rule: infra execution boxes are checked only with receipts in hand (proof JSON + verify output).
- Note: check “Proof run executed” only after `state/proofs/<run_id>.json` exists locally and `verify_published_s3` is OK.
  - Evidence required:
    - JOBINTEL_RUN_ID log line captured
    - `state/proofs/<run_id>.json` exists locally
    - `verify_published_s3` outputs OK (runs + latest)
- Note: check “EKS bootstrap path exists” only after a human-run `terraform init/plan/apply` completes and outputs are used to render the overlay.
- [x] Define object-store key structure + latest semantics + retention strategy:
  - `s3://<bucket>/runs/<run_id>/<provider>/<profile>/...`
  - `s3://<bucket>/latest/<provider>/<profile>/...`
- [x] Add `ops/aws/README.md` with:
  - required env vars/secrets (Discord webhook, AI keys, dashboard URL)
  - ECS taskdef + EventBridge schedule steps
  - IAM least-privilege policy (task role + operator verify role)
  - CloudWatch logs + metrics basics
- [x] Add `ops/aws/infra/` scaffolding (Terraform or CDK — pick one; keep minimal)
- [x] Add a “deployment smoke” script to validate AWS env vars and connectivity
- [x] Add a published-artifact verification script (`scripts/verify_published_s3.py`) and CI-friendly checks (optional)

---

## Milestone 2.5 — Provider Expansion (Safe, Config-Driven, Deterministic)

**Goal:** Add multiple AI companies without turning this into a scraper-maintenance job.

**Core rule:** no “LLM as scraper” unless cached, schema-validated, deterministic, and fail-closed.

### Definition of Done (DoD)
- [ ] Provider registry supports adding a new company via configuration:
  - name, careers URL(s), extraction mode, allowed domains, update cadence
- [ ] Extraction has a deterministic primary path (API/structured HTML/JSON-LD) when possible
- [ ] Optional LLM fallback extraction exists only with guardrails:
  - temperature 0, strict JSON schema, parse+validate, cache keyed by page hash,
    and “unavailable” on parse failures (no best-effort junk)
- [ ] A new provider can be added with ≤1 small code change (ideally none) + a config entry.

### Work Items
- [ ] Define provider config schema (YAML/JSON) and loader
- [ ] Implement a “safe extraction” interface:
  - `extract_jobs(html) -> List[JobStub]` deterministic
- [ ] Add at least 2 additional AI companies using the config mechanism

---

## Milestone 3 — History & intelligence (identity, dedupe, trends + user state)

**Goal:** track jobs across time, reduce noise, and make changes meaningful.

### Definition of Done (DoD)
- [ ] `job_identity()` produces stable IDs across runs for the same posting
- [x] URL normalization reduces false deltas
- [ ] Dedupe collapse: same job across multiple listings/URLs → one canonical record
- [ ] “Changes since last run” uses identity-based diffing (not just row diffs)
- [ ] History directory grows predictably (retention rules)
- [ ] **User State overlay** exists and affects outputs:
  - applied / ignore / interviewing / saved, etc.
  - shortlist + alerts respect this state (filter or annotate)

### Work Items
- [ ] Implement/validate identity strategy (title/location/team + URL + JD hash fallback)
- [ ] Store per-run identity map + provenance in `state/history/<profile>/...`
- [ ] Identity-based diffs for new/changed/removed
- [ ] Implement `state/user_state/<profile>.json` overlay:
  - schema: `{ "<job_id>": { "status": "...", "date": "...", "notes": "..." } }`
  - integrate into shortlist writer and alerting (filtering semantics defined)
- [ ] Retention policy (keep last N runs + daily snapshots) documented and enforced

---

## Milestone 3.5 — Semantic Safety Net (Deterministic Discovery)

**Goal:** Catch “good fits with weird wording” without losing explainability.

**Rule:** Semantic similarity is a bounded booster / classifier safety net, not a replacement for explainable rules.

### Definition of Done (DoD)
- [ ] Deterministic embedding path (fixed model + stable text normalization)
- [ ] Similarity used as bounded adjustment or relevance floor
- [ ] Thresholds are testable + documented
- [ ] Artifacts include similarity evidence

### Work Items
- [ ] Embedding cache + cost controls (max jobs embedded per run)
- [ ] Tests for deterministic similarity behavior + threshold boundaries

---

## Milestone 4 — Hardening & scaling (providers, cost controls, observability)

**Goal:** resilient providers, predictable cost, better monitoring.

### Definition of Done (DoD)
- [ ] Provider layer supports retries/backoff + explicit unavailable reasons
- [ ] Rate limiting / quota controls enforced
- [ ] Observability: CloudWatch metrics/alarms + run dashboards
- [ ] Optional caching backend (S3 cache for AI outputs/embeddings)
- [ ] Log sink + rotation strategy documented

### Work Items
- [ ] Provider abstraction hardening (Ashby + future providers) with snapshot/live toggles
- [ ] Cost controls: sampling, max jobs enriched, max AI tokens per run
- [ ] Log sink + rotation strategy documented

---

## Milestone 5 — Multi-user (Phase 2/3) — Profiles, uploads, and per-user experiences

**Goal:** other people can use the engine safely, with isolation and a clean UX.

### Definition of Done (DoD)
- [ ] Multiple candidate profiles supported:
  - profiles stored under `state/candidates/<candidate_id>/candidate_profile.json`
  - runs and user_state isolated per candidate/profile
- [ ] Resume/job-profile ingestion:
  - user uploads resume (PDF/DOCX/text) or fills structured job interests
  - pipeline produces a normalized `candidate_profile.json` (schema-validated)
- [ ] UI authentication and authorization (basic, practical)
- [ ] AI insights become profile-aware (coach-like, but grounded in artifacts)
- [ ] Security Review (Multi-Model)
- [ ] Move into Rancher/NV? Rancher desktop?
- [ ] Actual GUI?
- [ ] Linkedin page instead of resume for ingestion?
- [ ] interact with data on web (tables etc)
- [ ] Alternatives to discord? (email etc)
- [ ] expanded job category tuning and selectability

### Work Items
- [ ] Candidate profile schema versioning + validation
- [ ] Ingestion scripts: `scripts/ingest_resume.py` (Phase 2), `scripts/create_candidate.py`
- [ ] “Job interests” config: role families, locations, remote preference, seniority bands
- [ ] Isolation rules in run registry, artifact keys, S3 paths
- [ ] UI foundations (Phase 2): minimal front-end that sits on top of the API

---

## AI Roadmap (explicit, so it stays “last-mile”)

### Phase 1 AI (done/ongoing)
- [x] Weekly AI insights report (cached, schema’d, fail-closed, opt-in)
- [ ] Improve insights quality using more structured inputs:
  - diffs, top families, common skill gaps, location/seniority trends
- [ ] Add “AI insights per run” toggle (still bounded + cached)

### Phase 2 AI
- [ ] Profile-aware AI coaching:
  - what to look for this week, what to learn, what to highlight on resume
- [ ] Per-job AI briefs:
  - why it matches, likely interview focus areas, suggested resume bullets, questions to ask
- [ ] Still guardrailed:
  - cache keyed by job_id + jd hash + profile hash + prompt version
  - schema validation
  - deterministic settings

---

## Non-goals (right now)
- Big UI build until Milestone 2 (scheduled runs + object-store publishing) is solid
- Provider explosion until identity + history are stable (except targeted additions)
- “LLM as scraper” without strict guardrails and caches

---

## Backlog Parking Lot (ideas that can wait)
- Fancy dashboards (search, charts, actions) beyond minimal API
- Multi-candidate UX and resume ingestion
- AI outreach automation (email drafts, networking messages)
- Advanced analytics across providers once history is stable
