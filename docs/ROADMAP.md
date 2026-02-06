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

## Milestone 2 — Determinism Contract & Replayability (Local Truth > Vibes)

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

## Milestone 3 — Scheduled run + object-store publishing (Kubernetes CronJob first)

**Goal:** “It runs itself.” A Kubernetes CronJob (or equivalent orchestrator) runs daily, publishes to an
S3-compatible object store, optional alerts.

### Definition of Done (DoD)
- [x] Kubernetes CronJob runs end-to-end with mounted/ephemeral state
- [x] Publish plan + offline verification contract exists for object-store keys (verifiable allowlist)
- [x] End-to-end publish to a real object-store bucket verified (runs + latest keys)
- [x] Discord alerts sent only when diffs exist (or optionally always send summary; configurable)
- [x] Minimal object-store IAM policy documented (least privilege; AWS example)
- [ ] Live scraping verified in-cluster (EKS) with provenance showing live_attempted=true and live_result=success (not skipped/failed) — run + commit proof log
- [ ] Scrape politeness, rate limiting, and anti-bot hardening implemented (required before adding more providers)
- [x] Domain-backed dashboard endpoint (API first; UI can come later)
- [x] Runbook: deploy, inspect last run, roll back, rotate secrets
 - [ ] Proof artifacts captured (for verification):
   - CloudWatch log line with `run_id`
   - Provenance JSON line captured showing `live_attempted=true` and `live_result != skipped`
   - `ops/proof/liveproof-<run_id>.log` captured (contains JOBINTEL_RUN_ID + [run_scrape][provenance])
   - Provenance line shows `scrape_mode=live`, `snapshot_used=false`, `parsed_job_count` captured
   - Logs show `s3_status=ok` and `PUBLISH_CONTRACT pointer_global=ok`
   - Live proof manifest stored in repo: `ops/k8s/jobintel/jobs/jobintel-liveproof.job.yaml`
   - `s3://<bucket>/<prefix>/runs/<run_id>/<provider>/<profile>/...` populated
   - `python scripts/verify_published_s3.py --bucket <bucket> --run-id <run_id> --verify-latest` outputs OK

Current Status:
- Remaining Milestone 2 blockers are receipt-driven: in-cluster live proof, proof artifacts capture (`state/proofs/<run_id>.json` + verify output), and evidence that politeness signals (rate-limit/backoff/circuit-breaker + robots/allowlist) are present in real run logs/provenance.
- Deployment surfaces are in place (`ops/k8s/jobintel/dashboard.yaml`, `ops/k8s/RUNBOOK.md`, `src/ji_engine/dashboard/app.py`); remaining work is operational proof completion.

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
- [x] Scrape Politeness, Rate Limiting & Anti-Bot Hardening (required before adding more providers)
- [x] Per-provider politeness policy enforced (global QPS + per-host concurrency caps + jitter), recorded in provenance
- [x] Deterministic exponential backoff for transient failures (max retries + max sleep), recorded in logs
- [x] Circuit breaker: after N consecutive failures, pause LIVE attempts for cool-down window; degrade to snapshot-only per provider; surface in provenance
- [x] Robots/policy handling: log decision + allowlist (do not silently ignore)
- [x] Bot/deny-page detection: detect CAPTCHA/Cloudflare/access denied/empty-success; feed availability + circuit breaker
- [x] User-Agent discipline: explicit UA string + contact-ish metadata (if appropriate) and consistent across requests
- [ ] Proof requirements: provenance shows rate_limit policy applied; logs show backoff/circuit-breaker events; robots/allowlist decision recorded; test plan captured
- [x] Unit test: backoff + circuit-breaker decisions are deterministic given failure sequence
- [ ] In-cluster proof: live run logs include rate-limit/backoff/circuit-breaker events for at least one provider
- [ ] Proof run executed (EKS one-off job + real S3 publish + proof JSON captured) — proof JSON not yet captured locally
- [ ] EKS bootstrap path exists (Terraform) + IRSA wiring documented
- [ ] EKS can pull image (ECR golden path documented + working)
- Receipts rule: infra execution boxes are checked only with receipts in hand (proof JSON + verify output).
- Note: check “Proof run executed” only after `state/proofs/<run_id>.json` exists locally and `verify_published_s3` is OK.
  - Evidence required:
    - JOBINTEL_RUN_ID log line captured
    - `state/proofs/<run_id>.json` exists locally
    - `verify_published_s3` outputs OK (runs + latest)
- Note: check “EKS bootstrap path exists” only after a human-run `terraform init/plan/apply` completes and outputs are used to render the overlay.
- Receipts — run_id: `2026-02-05T02:35:34.028118+00:00`
- Receipts — s3 latest prefix: `s3://my-real-jobintel-bucket/jobintel/latest/openai/cs/`
- Receipts — s3 run prefix: `s3://my-real-jobintel-bucket/jobintel/runs/2026-02-05T02:35:34.028118+00:00/openai/cs/`
- Receipts — pointer path: `s3://my-real-jobintel-bucket/jobintel/state/last_success.json`
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

## Milestone 4 — On-Prem Primary (k3s) + Cloud DR (AWS) Without Babysitting

**Intent:** Move JobIntel to an **on-prem primary runtime** (Raspberry Pi k3s) with a **cloud disaster-recovery path** (AWS) that is **validated, rehearsed, and reproducible** — without turning AWS into a permanently running cost sink, and without creating a fragile “active/active” science project.

**Principles / Non-Goals (keep us honest):**
- ✅ **Primary execution on-prem** (k3s). Cloud is **cold standby** / DR only.
- ✅ **Deterministic rebuild**: infra + k8s + app comes up from code + backups.
- ✅ **Backups are boring**: scheduled, encrypted, checksummed, and tested.
- ✅ **Upgrades are routine**: simple runbooks, no heroics.
- ❌ No active/active between on-prem and cloud.
- ❌ No dual-write / live replication complexity.
- ❌ No permanent “always-on” EKS as the normal operating model.

### Definition of Done (DoD)
This milestone is complete only when all items below are **true and proven with artifacts**:

#### 1) On-Prem k3s Cluster is Operational + Documented
- [ ] k3s cluster (3x Pi4, 8GB each) runs stable for 72h with:
  - [ ] control plane stable (no crash loops / repeated restarts)
  - [ ] node readiness stable (no flapping, no frequent NotReady)
  - [ ] time sync verified (NTP) and consistent across nodes
- [ ] Storage strategy implemented:
  - [ ] **Primary storage** on USB3 1TB for stateful data (not SD)
  - [ ] SD used only for OS boot (or documented if otherwise)
  - [ ] filesystem choice documented (e.g., ext4) + mount options
  - [ ] clear capacity expectations: DB size growth, artifact growth
- [ ] Networking baseline documented:
  - [ ] LAN assumptions and DHCP/static IP plan
  - [ ] DNS + local name resolution strategy
  - [ ] ingress strategy (see section 4)
- [ ] k3s install is automated / reproducible:
  - [ ] scripts or IaC-style automation (idempotent)
  - [ ] pinned versions (k3s + critical components)
  - [ ] upgrade plan documented + tested at least once in a safe rehearsal

#### 2) Cluster Management Strategy Chosen and Hardened (Rancher Optional but Supported)
Choose **one** as the default path and keep the others as optional:

**Option A (Lean):** “kubectl + GitOps” (default for lowest maintenance)
- [ ] GitOps tool chosen (Flux or ArgoCD) and deployed OR explicit rationale for not using
- [ ] cluster state fully described by manifests in repo (excluding secrets)

**Option B (Operable UI):** Rancher manages k3s cluster
- [ ] Rancher installed in a dedicated namespace
- [ ] k3s cluster imported/managed and health is green
- [ ] access model documented (local admin, SSO optional)
- [ ] clear statement on what Rancher is used for:
  - [ ] visibility + upgrades + cluster lifecycle
  - [ ] NOT a dumping ground for manual drift

**DoD requirement regardless of option:**
- [ ] “Single source of truth” is explicit (Git is truth; UI changes must reconcile back)
- [ ] Manual UI-only changes are treated as a failure condition (documented)

#### 3) “Low Maintenance” Guardrails Implemented (No Regular Babysitting)
- [ ] Observability baseline exists:
  - [ ] log access is easy (kubectl logs + centralized option documented)
  - [ ] core health check commands documented and fast (<5 minutes)
- [ ] Node health is self-healing where feasible:
  - [ ] k3s service auto-restart enabled and validated
  - [ ] kubelet/container runtime stability verified
- [ ] Upgrade discipline codified:
  - [ ] “upgrade checklist” runbook exists
  - [ ] “rollback / restore” runbook exists
- [ ] Maintenance boundaries defined:
  - [ ] what will be upgraded on schedule (k3s, app image, add-ons)
  - [ ] what is “as-needed” (Rancher, OS packages)
  - [ ] what is intentionally NOT part of scope (active/active replication)

#### 4) Ingress + TLS + DNS: Production-Grade but Not Fancy
- [ ] Ingress chosen and deployed (Traefik default for k3s is fine, or NGINX if preferred)
- [ ] TLS strategy implemented:
  - [ ] local CA or Let’s Encrypt (document constraints if no public DNS)
  - [ ] cert rotation and renewal documented + validated
- [ ] DNS strategy:
  - [ ] local DNS (Pi-hole / router DNS / internal) OR public DNS if exposed
- [ ] Access strategy for “home/office” vs “away” documented:
  - [ ] preferred: VPN (Tailscale/WireGuard) to avoid exposing services publicly
  - [ ] explicitly disallow “random open ports” without a documented reason

#### 5) App Runs on k3s: CronJob-First, Kubernetes-Native (CNCF discipline)
- [ ] JobIntel runs as a Kubernetes CronJob on k3s
- [ ] All required secrets/config are Kubernetes-native:
  - [ ] Secrets stored as encrypted at rest (SOPS/age preferred) OR clear alternative documented
  - [ ] ConfigMaps for non-sensitive configs
- [ ] Storage and state:
  - [ ] `state/` and proof artifacts persist across pod restarts
  - [ ] DB is stateful (Postgres) with persistent volume claims
- [ ] “No drift” deployment:
  - [ ] manifests templated (kustomize/helm) and tracked in repo
  - [ ] deploy is one command (or one GitOps sync)

#### 6) Backup System (On-Prem → Cloud) is Implemented, Encrypted, and Tested
Backups must cover the “four truths”:
1) **Database** (Postgres)
2) **Artifacts / state** (proofs, snapshots, outputs)
3) **Manifests / config** (Git)
4) **Infra definition** (IaC / scripts)

**Requirements:**
- [ ] DB backups:
  - [ ] scheduled `pg_dump` (or pg_basebackup if justified)
  - [ ] compressed + encrypted
  - [ ] retention policy (e.g., daily 14 days, weekly 8 weeks)
- [ ] Artifact backups:
  - [ ] `state/` + proof receipts + published outputs (as applicable)
  - [ ] checksummed (hash manifest) and verified after upload
- [ ] Offsite target:
  - [ ] AWS S3 bucket with versioning enabled
  - [ ] least-privilege IAM user/role credentials
  - [ ] SSE-S3 or SSE-KMS + documented key ownership
- [ ] Restore test:
  - [ ] at least one full restore to a clean environment (local or cloud)
  - [ ] evidence captured (timestamps, run IDs, checksums)

#### 7) Cloud DR Path is Real (Cold Standby), Proven Once, and Tear-Down Friendly
The goal is **rebuild on demand**, not “always-on cloud.”

- [ ] DR infrastructure definition exists (Terraform or equivalent):
  - [ ] Either:
    - [ ] EKS minimal cluster definition, or
    - [ ] EC2 + k3s (cheaper and simpler for “cold standby”)
- [ ] DR runbook exists: “from zero to running JobIntel”
  - [ ] provision infra
  - [ ] deploy manifests
  - [ ] restore DB + artifacts
  - [ ] validate a job run
  - [ ] tear down cloud infra
- [ ] DR rehearsal performed end-to-end at least once:
  - [ ] evidence captured (logs, output artifacts)
  - [ ] teardown succeeded and verified (no lingering spend)

#### 8) Runbooks: Normal Ops, Upgrades, Disaster Recovery
Minimum required runbooks:
- [ ] `RUNBOOK_ONPREM_INSTALL.md` (k3s bootstrap, storage, networking)
- [ ] `RUNBOOK_DEPLOY.md` (deploy app, rotate secrets, inspect last run)
- [ ] `RUNBOOK_UPGRADES.md` (k3s + add-ons + app image)
- [ ] `RUNBOOK_BACKUPS.md` (what is backed up, schedule, retention, restore steps)
- [ ] `RUNBOOK_DISASTER_RECOVERY.md` (AWS cold start restore + validation + teardown)
- [ ] Each runbook includes:
  - [ ] preflight checks
  - [ ] success criteria
  - [ ] “if it fails” branches
  - [ ] commands that can be copy/pasted

#### 9) Evidence / Proof Artifacts (So This Isn’t Just “It Works On My Desk”)
- [ ] Proof artifacts stored in repo or documented location:
  - [ ] backup success logs + checksum verification output
  - [ ] restore proof (DB restored + artifacts present)
  - [ ] DR rehearsal proof (cloud came up, run executed, outputs produced)
- [ ] All evidence references run_id and timestamps.

---

### Implementation Notes / Guardrails (Hard Rules)
- No manual “clickops drift”: if UI is used (Rancher/AWS console), the final state must be reflected back into code or documented as intentional.
- Cloud DR must be “cheap by default”:
  - keep nodes scaled to zero where possible
  - use teardown as part of rehearsal
- Security baseline:
  - no plaintext secrets in repo
  - no long-lived admin keys without rotation plan
- Upgrade safety:
  - always validate add-on versions compatibility (coredns, vpc-cni, kube-proxy if applicable)
  - keep rollback options clear (restore from backup beats fiddling)

---

### Deliverables (Repo Artifacts)
- [ ] `ops/onprem/`:
  - [ ] k3s install scripts or automation
  - [ ] storage setup notes/scripts
  - [ ] networking notes (ingress/DNS/VPN)
- [ ] `ops/dr/`:
  - [ ] Terraform (EKS or EC2+k3s) OR equivalent reproducible infra code
  - [ ] teardown scripts
- [ ] `ops/runbooks/` (or `ops/k8s/` if that’s your existing convention):
  - [ ] all runbooks listed above
- [ ] `scripts/ops/`:
  - [ ] backup script(s) (db + artifacts) with encryption + verification
  - [ ] restore script(s)
  - [ ] DR bring-up + validate + teardown orchestration script

---

### Acceptance Test (Single Command “Prove It”)
A “prove it” sequence exists that can be run by Future You:
- [ ] On-prem:
  - [ ] deploy
  - [ ] run a scrape/job
  - [ ] confirm outputs + proof receipts
  - [ ] run backups
- [ ] DR rehearsal:
  - [ ] bring up cloud infra
  - [ ] restore
  - [ ] run job
  - [ ] verify outputs
  - [ ] teardown cloud infra

Milestone 4 is DONE when the above is rehearsed once end-to-end and you can repeat it without discovering surprise tribal knowledge.

---

## Milestone 5 — Provider Expansion (Safe, Config-Driven, Deterministic)

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

## Milestone 6 — History & intelligence (identity, dedupe, trends + user state)

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

## Milestone 7 — History & intelligence (identity, dedupe, trends + user state)

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

## Milestone 8 — Semantic Safety Net (Deterministic Discovery)

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

## Milestone 9 — Hardening & scaling (providers, cost controls, observability)

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

## Milestone 10 — Multi-user (Phase 2/3) — Profiles, uploads, and per-user experiences

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
