© 2026 Chris Menendez. Source Available — All Rights Reserved.  
This repository is publicly viewable but not open source.  
See LICENSE for permitted use.

# SignalCraft Roadmap

This roadmap is the anti-chaos anchor.  
We optimize for:

1) Deterministic outputs  
2) Debuggability  
3) Deployability  
4) Incremental intelligence  
5) Productization without chaos  

If a change doesn’t advance a milestone’s Definition of Done (DoD), it’s churn.

---

# Document Contract

**This file is the plan. The repo is the truth.**

Every merged PR must:
- Declare which milestone moved
- Include evidence paths (tests, logs, proof bundles)
- Keep “Current State” aligned with actual behavior

Roadmap discipline lives in:
`docs/CONTRIBUTING_ROADMAP_DISCIPLINE.md`

---

# Non-Negotiable Guardrails

- One canonical pipeline entrypoint (`scripts/run_daily.py`)
- Determinism > cleverness
- Explicit input selection reasoning
- Small, test-backed changes
- Operational truth lives in artifacts
- AI is last-mile only
- No credentialed scraping
- Legal constraints enforced in design
- CI must prove determinism offline
- Cloud runs must be replayable locally
- Milestone completion requires receipts

---

# Legal + Ethical Operation Contract

SignalCraft is a **discovery and alerting net**, not a job board replacement.

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

---

# Current State

Last verified: **2026-02-13T01:00:59Z @ 555b095292109864c3016a52084e78e6616bd9d6**  
Latest release: **v0.1.0**

Phase 1 foundation exists:
- Deterministic scoring
- Replayability
- Snapshot-backed providers
- Discord alerts
- Dashboard API (minimal)
- AI weekly insights (guardrailed)
- Semantic sidecar/boost modes
- Cost guardrails
- CI smoke enforcement

Phase 1 is real.

---

# ARCHIVE — Milestones 1–9

(unchanged logic; preserved as completed foundation)

---

# NEW ROADMAP — Thick Milestones

---

## Milestone 10 — Provider Platform v1

**Goal:** Provider expansion becomes boring.

### Definition of Done

- [ ] Versioned provider registry schema exists
- [ ] Config validation tests enforce registry correctness
- [ ] Provider addition requires no core refactor
- [ ] Snapshot fixtures enforced for every enabled provider
- [ ] Provider tombstone supported
- [ ] Provenance records registry hash/version
- [ ] At least 3 additional providers added via registry

### Receipts Required

- Proof doc in `docs/proof/m10-provider-platform-v1-<date>.md`
- Deterministic ordering tests
- Snapshot completeness enforcement tests

---

## Milestone 11 — Artifact Model v2 (UI-Safe vs Replay-Safe)

**Goal:** Legality and UX enforced by artifact shape.

### Definition of Done

- [ ] UI-safe artifact schema defined
- [ ] Replay-safe artifact schema defined
- [ ] Dashboard and alerts use UI-safe artifacts only
- [ ] UI-safe artifacts contain no raw JD text
- [ ] Retention policy documented
- [ ] Tests enforce redaction boundaries

### Receipts Required

- Proof doc
- Schema validation tests
- Privacy enforcement test suite

---

## Milestone 12 — Operations Hardening Pack

**Goal:** Failure is explicit and inspectable.

### Definition of Done

- [ ] Every run writes costs + provenance + report
- [ ] failed_stage always populated on error
- [ ] One-command run inspection tooling exists
- [ ] Provider availability summary artifact generated
- [ ] CI smoke aligned with real run shape
- [ ] Failure playbook documented

### Receipts Required

- Forced provider failure proof
- Artifact showing explicit failure stage

---

## Milestone 13 — AI Insights v1 (Useful Intelligence)

**Goal:** Weekly insights are grounded and actionable.

### Definition of Done

- [ ] Structured deterministic input schema versioned
- [ ] 7/14/30 day trend analysis
- [ ] Top recurring skill tokens derived from structured fields
- [ ] Output validated against strict schema
- [ ] Cache keyed by input hash + prompt version
- [ ] “Top 5 Actions” section included
- [ ] No raw JD leakage

### Receipts Required

- Two-run deterministic diff proof
- Schema validation test suite

---

## Milestone 14 — AI Per-Job Briefs v1

**Goal:** Profile-aware coaching per job.

### Definition of Done

- [ ] Candidate profile hash contract defined
- [ ] ai_job_brief.schema.json implemented
- [ ] Brief generation bounded by cost guardrails
- [ ] Caching keyed by job_id + job_hash + profile_hash
- [ ] Output schema validated
- [ ] Deterministic hash stability verified

### Receipts Required

- Deterministic output proof
- Cost accounting artifact integration

---

## Milestone 15 — Explainability v1

**Goal:** Scores are interpretable.

### Definition of Done

- [ ] explanation_v1 structure in UI-safe artifacts
- [ ] Top contributing signals surfaced
- [ ] Penalties visible
- [ ] Semantic contribution bounded + visible
- [ ] Ordering deterministic

### Receipts Required

- Artifact snapshot proof
- Ordering determinism tests

---

## Milestone 16 — Dashboard Plumbing v2

**Goal:** Backend-first UI readiness.

### Definition of Done

- [ ] /version endpoint implemented
- [ ] /runs/latest endpoint implemented
- [ ] Artifact index endpoint implemented
- [ ] API contract documented in docs/API.md
- [ ] Optional dashboard deps isolated cleanly

### Receipts Required

- API proof doc
- Minimal UI simulation proof

---

## Milestone 17 — Release Discipline v1

**Goal:** Releases are reproducible proof events.

### Definition of Done

- [ ] Release checklist exists
- [ ] Preflight validation script exists
- [ ] Changelog discipline enforced
- [ ] Each release has proof doc

---

## Milestone 18 — On-Prem Execution Proof

**Goal:** 72-hour stability receipt.

### Definition of Done

- [ ] 72-hour k3s stability logs captured
- [ ] USB storage verified
- [ ] Backup + restore rehearsal documented
- [ ] CronJob receipts captured

---

## Milestone 19 — Compliance / Policy Pack

**Goal:** Legality enforced by code + tests.

### Definition of Done

- [ ] Policy docs align with implementation
- [ ] Security review checklist exists
- [ ] Redaction enforcement test suite exists
- [ ] Provider allowlist enforcement tested

---

## Milestone 20 — Phase 2 Launchpad (Multi-User Plumbing Only)

**Goal:** Prepare without building UI.

### Definition of Done

- [ ] candidate_profile.schema.json defined
- [ ] candidate_id integrated into run registry
- [ ] Artifact path namespaced
- [ ] Backwards compatibility maintained
- [ ] No UI yet

---

# Phase 3 Preview (21–30)

High-level product direction only.

- Multi-user auth
- Resume ingestion
- Real UI
- AI coaching
- AI outreach
- Advanced analytics
- Alert expansion
- Provider scaling
- Cost optimization
- Architecture pruning

---

# Milestone Philosophy

Fewer, thicker milestones > tiny checklists.

Each milestone must:
- Produce artifacts
- Produce tests
- Produce receipts
- Reduce chaos
- Increase product clarity
