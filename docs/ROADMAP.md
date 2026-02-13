© 2026 Chris Menendez. Source Available — All Rights Reserved.
See LICENSE for permitted use.

# SignalCraft Roadmap

SignalCraft is a deterministic, reproducible career intelligence platform.

- **SignalCraft = product surface**
- **JIE = deterministic engine core**

This roadmap is the anti-chaos anchor.
We optimize for:

1) Deterministic outputs
2) Debuggability
3) Deployability
4) Incremental intelligence
5) Productization without chaos
6) Infrastructure portability (cloud + on-prem)

If a change doesn’t advance a milestone’s Definition of Done (DoD), it’s churn.

---

# Document Contract

This file is the plan. The repo is the truth.

Every merged PR must:
- Declare which milestone moved
- Include evidence paths (tests, logs, proof bundles)
- Keep “Current State” aligned with actual behavior
- Preserve determinism contracts and replay guarantees

---

# Non-Negotiable Guardrails

- One canonical pipeline entrypoint (`scripts/run_daily.py`)
- Determinism > cleverness
- Contract-driven artifacts (schema versioning is mandatory)
- Replayability must work offline
- Operational truth lives in artifacts
- AI is last-mile augmentation only (bounded, cached, fail-closed)
- No credentialed scraping
- Legal constraints enforced in design
- CI must prove determinism and safety properties
- Cloud runs must be replayable locally
- Multi-user must never become a rewrite: **namespace first, features later**
- Milestone completion requires receipts

---

# Legal + Ethical Operation Contract

SignalCraft is a discovery and alerting net, not a job board replacement.

Hard rules:
- Canonical outbound links always included
- UI-safe artifacts never replace original job pages
- Robots and policy decisions logged in provenance
- Per-host rate limits enforced
- Opt-out supported via provider tombstone
- Honest, stable User-Agent
- No paywall bypass or login scraping

Evidence expectations:
- Provenance includes scrape_mode + policy decision
- Provider availability reasons surfaced explicitly
- Artifact model ensures UI-safe outputs remain legally conservative

---

# Current State

Last verified: 2026-02-13 (local verification; see git + CI receipts)
Latest release: v0.1.0

Foundation exists:
- Deterministic scoring
- Replayability
- Snapshot-backed providers
- AI weekly insights (guardrailed)
- Per-job briefs
- Cost guardrails
- Discord alerts
- Dashboard API
- CI smoke enforcement

**Recent structural improvements (productization enablers):**
- Candidate namespace reservation (default `local`) to prevent future multi-user rewrite
- Dashboard artifact read hardening (bounded JSON reads + schema checks)
- RunRepository seam (filesystem-backed now; enables future indexing later)

Phase 1 is real.

---

# Roadmap Philosophy

Fewer, thicker milestones.

Every milestone must:
- Produce artifacts
- Produce tests
- Produce receipts
- Reduce chaos
- Increase product clarity
- Increase infrastructure resilience

---

# NEW ROADMAP — Thick Milestones

## Milestone 10 — Provider Platform v1 (Boring Expansion)

Goal: Provider expansion becomes boring and safe.

Definition of Done
- [ ] Versioned provider registry schema exists
- [ ] Registry hash recorded in provenance
- [ ] Provider config validated in CI (schema + invariants)
- [ ] Snapshot fixtures enforced per provider
- [ ] Provider tombstone supported (opt-out / takedown path)
- [ ] At least 3 new providers added via registry-only changes
- [ ] No core pipeline modification required to add a provider
- [ ] Provider ordering deterministic across runs

Receipts Required
- Deterministic ordering tests
- Snapshot completeness enforcement tests
- Proof doc in `docs/proof/`

---

## Milestone 11 — Artifact Model v2 (Legal + UI-Safe by Design)

Goal: Legality + replayability enforced by shape.

Definition of Done
- [ ] UI-safe artifact schema versioned
- [ ] Replay-safe artifact schema versioned
- [ ] UI-safe artifacts contain no raw JD text (or strictly bounded excerpts if policy allows)
- [ ] Redaction boundaries enforced by tests (stdout/logs included)
- [ ] Retention policy documented (what is stored, for how long, why)
- [ ] Artifact backward compatibility defined (and tested)
- [ ] Artifact provenance includes provider policy decision + canonical URL

Receipts Required
- Schema validation suite
- Redaction + “no raw JD” test suite
- Proof doc

---

## Milestone 12 — Operations Hardening Pack v1 (Explicit Failure + Inspectability)

Goal: Failure is explicit and inspectable.

Definition of Done
- [ ] `failed_stage` always populated on failure
- [ ] Cost telemetry always written (even on partial failure)
- [ ] Provider availability artifact generated every run
- [ ] One-command run inspection tooling (human-friendly)
- [ ] CI smoke matches real run structure
- [ ] Failure playbook updated
- [ ] **Candidate namespace is treated as first-class (default `local`)**:
  - candidate_id flows through orchestration
  - artifacts + pointers do not collide across candidates
  - backward compatibility policy documented

Receipts Required
- Forced failure proof run (with artifacts)
- Artifact inspection proof
- Candidate isolation proof artifacts/tests

---

## Milestone 13 — Run Indexing v1 (Metadata Without Rewrites)

Goal: Remove “filesystem-as-database” pain without abandoning artifacts.

Rationale: Artifacts stay as blobs. Indexing is metadata only.

Definition of Done
- [ ] RunRepository seam is the only way to resolve runs (no scattered path-walking)
- [ ] A minimal index exists for O(1) “latest run” + recent run listing:
  - Option A (preferred on-prem friendly): SQLite index in state (single-writer safe)
  - Option B (cloud friendly): DynamoDB / Postgres later (not required now)
- [ ] Index is append-only and derived from artifacts (rebuildable)
- [ ] Dashboard endpoints do not require directory scans for the common case
- [ ] Index rebuild tool exists (deterministic)

Receipts Required
- Index rebuild proof
- Determinism proof: index rebuild yields identical results
- Dashboard performance sanity proof (basic benchmark notes)

---

## Milestone 14 — AI Insights v1 (Grounded Intelligence, Bounded)

Goal: Weekly insights are useful and bounded.

Definition of Done
- [ ] Deterministic input schema versioned
- [ ] 7/14/30 day trend analysis
- [ ] Skill token extraction from structured fields (not raw JD)
- [ ] Strict output schema enforcement
- [ ] Cache keyed by input hash + prompt version
- [ ] “Top 5 Actions” section included
- [ ] No raw JD leakage

Receipts Required
- Two-run determinism proof
- Schema validation tests

---

## Milestone 15 — AI Per-Job Briefs v1 (Coaching Per Job, Deterministic Cache)

Goal: Profile-aware coaching per job.

Definition of Done
- [ ] Candidate profile hash contract defined
- [ ] `ai_job_brief.schema.json` enforced
- [ ] Cache keyed by job_hash + profile_hash + prompt_version
- [ ] Cost accounting integrated
- [ ] Deterministic hash stability verified
- [ ] Schema validation enforced in CI

Receipts Required
- Deterministic diff proof
- Cost artifact proof

---

## Milestone 16 — Explainability v1 (Make Scores Interpretable)

Goal: Scores are explainable and stable.

Definition of Done
- [ ] `explanation_v1` structure implemented
- [ ] Top contributing signals surfaced
- [ ] Penalties visible
- [ ] Semantic contribution bounded + surfaced (if used)
- [ ] Deterministic ordering enforced

Receipts Required
- Artifact snapshot proof
- Ordering tests

---

## Milestone 17 — Dashboard Plumbing v2 (Backend-First UI Readiness)

Goal: Backend is UI-ready without becoming UI-first.

Definition of Done
- [ ] `/version` endpoint
- [ ] `/runs/latest` endpoint is candidate-aware
- [ ] Artifact index endpoint(s) are stable and documented
- [ ] API contract documented
- [ ] Optional deps isolated cleanly
- [ ] Read-time validation is fail-closed and bounded

Receipts Required
- API proof doc
- Simulated UI proof (curl scripts + sample payloads)

---

## Milestone 18 — Release Discipline v1 (Releases Are Proof Events)

Goal: Releases are evidence-backed.

Definition of Done
- [ ] Release checklist codified
- [ ] Preflight validation script exists
- [ ] Changelog enforcement policy
- [ ] Every release includes proof bundle
- [ ] Reproducible build instructions verified

Receipts Required
- One full release dry-run proof bundle

---

# INFRASTRUCTURE EVOLUTION

## Milestone 19 — AWS DR & Failover Hardening

Goal: Cloud execution survives failure.

Definition of Done
- [ ] S3 versioning enabled
- [ ] S3 lifecycle policy defined
- [ ] Backup bucket replication strategy documented
- [ ] Disaster recovery restore rehearsal executed
- [ ] RTO + RPO explicitly defined
- [ ] Infrastructure config versioned
- [ ] Recovery playbook tested

Receipts Required
- Restore rehearsal proof
- Recovery time measurement
- Backup verification artifact

---

## Milestone 20 — On-Prem Migration Contract (AWS → k3s)

Goal: Migration is engineered, not improvised.

Definition of Done
- [ ] Data migration plan documented
- [ ] Artifact compatibility verified
- [ ] Backwards compatibility test suite passes
- [ ] Rollback plan documented
- [ ] Dual-run validation (AWS vs on-prem output diff)
- [ ] Zero artifact schema changes required
- [ ] Migration dry run executed

Receipts Required
- Side-by-side artifact diff proof
- Migration dry run log
- Rollback rehearsal doc

---

## Milestone 21 — On-Prem Stability Proof (Post-Migration)

Goal: On-prem becomes primary without chaos.

Definition of Done
- [ ] 72-hour continuous k3s run
- [ ] CronJob stability verified
- [ ] Storage durability verified
- [ ] Backup + restore rehearsal on-prem
- [ ] Resource utilization captured
- [ ] Determinism validated against AWS baseline
- [ ] Failure injection rehearsal (kill pod, restart node)

Receipts Required
- Stability logs
- Restore proof
- Deterministic diff proof

---

# GOVERNANCE & PRODUCTIZATION PREREQS

## Milestone 22 — Security Review Pack v1 (Audited Posture)

Goal: Security posture is audited, not assumed.

Definition of Done
- [ ] Threat model document created (multi-tenant aware)
- [ ] Attack surface review performed
- [ ] Secrets handling reviewed + redaction tests enforced
- [ ] Dependency audit completed
- [ ] Least-privilege IAM documented (AWS + on-prem)
- [ ] Static analysis tool integrated
- [ ] SECURITY.md aligned with reality
- [ ] “User-supplied URL/provider” policy documented (SSRF/egress stance)

Receipts Required
- Threat model artifact
- Dependency audit report
- IAM review checklist

---

## Milestone 23 — Code Surface & Bloat Review (Entropy Reduction)

Goal: Eliminate entropy before adding product surfaces.

Definition of Done
- [ ] Dead code removed
- [ ] Unused deps removed
- [ ] Duplicate logic consolidated
- [ ] File structure rationalized
- [ ] Public API boundaries clarified
- [ ] Complexity hotspots documented
- [ ] Size diff documented

Receipts Required
- Before/after LOC diff
- Dependency tree comparison
- Simplification proof doc

---

## Milestone 24 — Multi-User Plumbing v1 (Foundation + Isolation)

Goal: Prepare for product without UI complexity.

Definition of Done
- [ ] `candidate_profile.schema.json` defined
- [ ] candidate registry exists (CRUD via file/CLI only; no web UI required)
- [ ] Candidate isolation enforced end-to-end (paths, pointers, index)
- [ ] Cross-user leakage tests implemented
- [ ] Audit trail artifacts exist (who/what triggered run; profile hash change record)
- [ ] Backward compatibility maintained for `local`
- [ ] No authentication/UI implemented yet

Receipts Required
- Isolation test suite
- Audit trail proof artifacts
- Backward compat proof

---

# Phase 3 Preview (25–35)

Product surface comes after plumbing and security receipts:
- Authentication + authz (RBAC)
- Resume/LinkedIn ingestion (strict SSRF + egress policy)
- Profile UX + presets (seniority, role archetypes)
- Alerts + digests (daily/weekly)
- AI coaching expansion (bounded, opt-in, costed)
- Billing/cost attribution readiness
- Provider scaling + maintenance tooling
- UI (only after API is boring)

---

## Archive — Milestones 1–9 (Completed)

This archive is retained for historical continuity; the active roadmap above remains canonical. These milestones are completed and superseded by the current structure and PR receipts.

# ARCHIVE — Milestones 1–9 (Completed / Superseded)

**Archive rule:** These milestones are “done enough” for Phase 1.  
Do not reopen unless a regression threatens determinism, replayability, or deployability.

## Milestone 1 — Daily run deterministic & debuggable (Local + Docker + CI) ✅
**Receipts:** see `docs/OPERATIONS.md`, CI smoke contracts, snapshot helpers.
- [x] `pytest -q` passes locally/CI
- [x] Docker smoke produces ranked outputs + run report
- [x] Exit codes normalized
- [x] Snapshot debugging helpers (`make debug-snapshots`)
- [x] CI deterministic artifact validation

## Milestone 2 — Determinism Contract & Replayability ✅
**Receipts:** `docs/RUN_REPORT.md`, `scripts/replay_run.py`, tests covering selection reasons + archival + `--recalc`.
- [x] Run report explains selection
- [x] Schema contract documented
- [x] Selected inputs archived per run
- [x] Replay workflow + hash verification

## Milestone 3 — Scheduled run + object-store publishing (K8s CronJob first) ✅
**Receipts:** proof bundles under `ops/proof/bundles/m3-*`, runbooks, publish/verify scripts.
- [x] CronJob runs end-to-end
- [x] S3 publish plan + offline verification
- [x] Real bucket publish verified (+ latest pointers)
- [x] Live scrape proof in-cluster
- [x] Politeness/backoff/circuit breaker enforced

## Milestone 4 — On-Prem primary + Cloud DR (proven once; stability pending) ◐
**Status:** Partially complete: backup/restore + cloud DR proven once, on-prem 72h stability not yet proven.
**Receipts:** `ops/proof/bundles/m4-*`, runbooks in repo.
- [x] Backup/restore rehearsal (encrypted + checksummed)
- [x] DR rehearsal end-to-end (bring up → restore → run → teardown)
- [ ] On-prem 72h stability receipts (blocked by hardware timing)

## Milestone 5 — Provider Expansion (config-driven, offline proof) ◐
**Status:** Offline multi-provider proof exists; “fully config-driven provider registry” still needs consolidation/hardening as a single coherent milestone (see Milestone 10 below).
**Receipts:** `docs/proof/m5-offline-multi-provider-2026-02-11.md`

## Milestone 6 — History & intelligence (identity, dedupe, user state) ✅
**Receipts:** `src/ji_engine/history_retention.py`, tests, `docs/OPERATIONS.md`.
- [x] Stable job identity + identity-based diffs
- [x] Retention rules enforced
- [x] User state overlay affects outputs and alerts

## Milestone 7 — Semantic Safety Net (deterministic) ✅ (Phase 1 scope)
**Receipts:** `docs/proof/m7-semantic-safety-net-offline-2026-02-12.md`, tests.
- [x] Deterministic embedding backend (hash backend) + cache
- [x] Sidecar + boost modes
- [x] Thresholds testable/documented
- [x] Evidence artifacts produced

## Milestone 8 — Hardening & scaling (Phase 1 subset done) ◐
**Status:** Several elements exist (cost guardrails, provider availability reasons, observability basics), but consolidation is needed (see Milestone 12).
- [x] Cost guardrails + costs artifact
- [x] Provider unavailable reasons surfaced
- [x] CI smoke gate failure modes documented
- [ ] Full “operational hardening pack” milestone still needed

## Milestone 9 — Multi-user (deferred to Phase 3) ⏸
**Status:** intentionally deferred; do not start UX/product complexity until Phase 2/3 tranche.

---
