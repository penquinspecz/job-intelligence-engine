© 2026 Chris Menendez. Source Available — All Rights Reserved.
This repository is publicly viewable but not open source.
See LICENSE for permitted use.

# SignalCraft Roadmap

This roadmap is the anti-chaos anchor. We optimize for:
1) deterministic outputs, 2) debuggability, 3) deployability, 4) incremental intelligence.

If a change doesn’t advance a milestone’s Definition of Done (DoD), it’s probably churn.

---

## Document Contract

**This file is the plan. The repo is the truth.**  
Every merged PR must:
- declare which milestone box(es) moved,
- cite evidence paths (tests, logs, proof bundles, artifacts),
- and keep “Current State” aligned with what actually runs.

**Roadmap discipline:** see `docs/CONTRIBUTING_ROADMAP_DISCIPLINE.md`.

---

## Principles / Guardrails (non-negotiable)

- **One canonical pipeline entrypoint:** `scripts/run_daily.py`
- **Determinism over cleverness:** same inputs → same outputs
- **Explicit input selection rules:** labeled vs enriched vs AI-enriched must be predictable
- **Small, test-backed changes:** no “refactor weeks” unless it buys a milestone
- **Operational truth lives in artifacts:** run metadata + logs + outputs > vibes
- **LLMs are allowed only with guardrails:** cache + schema + fail-closed + reproducible settings
- **AI is last-mile:** deterministic pipeline produces stable artifacts; AI reads them and produces insight outputs
- **Multi-candidate is later:** design plumbing now (paths/schemas), avoid UI complexity until Phase 1 is boring
- **Tests must be deterministic regardless of optional deps**
- **Single source of truth for dependencies:** Docker, CI, local install from the same contract
- **Docs are a contract:** README/ops docs must match runnable behavior
- **Cloud is not special:** AWS runs must be replayable and inspectable like local
- **Receipts required:** milestone completion means evidence exists in-repo

---

## Legal + Ethical Operation Contract (Product Constraint)

SignalCraft’s intent is to be a **discovery and alerting net**, not a replacement for employer career pages.

### Hard rules (must remain true as we evolve)
- **Always include canonical outbound links** to the original job posting and employer careers page.
- **Do not re-host full job descriptions** as the primary experience.
  - UI must emphasize summaries, signals, and diffs, and direct the user to the source for full details.
  - If raw JD text exists in artifacts for scoring/replay, it must be treated as internal pipeline data with hygiene controls (redaction + retention + access).
- **Respect robots/policies and site terms**:
  - Maintain allowlist/denylist decisions in config.
  - Log the policy decision in provenance; never “silently scrape.”
- **Politeness by default**: per-host rate limits, concurrency caps, jitter, backoff, and circuit breaker must remain enforced.
- **Opt-out support**: if a company requests exclusion, provider config must support disabling them cleanly (and future-proof for a “provider tombstone” record).
- **User-Agent honesty**: stable UA string identifying the project + repo contact URL.
- **No credentialed scraping** (logins, bypassing paywalls, defeating anti-bot) in core product scope.

### Evidence expectations
- Provenance includes robots/policy decision, scrape_mode, and whether snapshots were used.
- Provider availability reasons are explicit (deny-page, captcha, blocked, timeout, policy_skip, etc.).

---

## Product Intent (big-picture, so we don’t build the wrong thing)

### Phase 1 (now): “Useful every day, deployable via Kubernetes or cloud-agnostic schedulers”
- Daily run produces artifacts + run registry
- Discord notifications (deltas + top items)
- Minimal dashboard API to browse runs/artifacts
- Weekly AI insights report (cached, guarded, posted as a summary)
- Kubernetes CronJob deployment: scheduled runs + object-store publishing + domain-backed dashboard endpoint (AWS optional)

### Phase 2+: “Multi-user + powerful UX + deeper AI”
- Users upload resume/profile → their own scoring runs, alerts, and state
- Real UI: filters/search, explainability, lifecycle actions
- AI: profile-aware coaching + per-job recommendations + outreach suggestions (still guardrailed/cached)

---

## Current State (Update this when reality changes)

Last verified: **2026-02-12T23:35:20Z @ 0a7161cc5c74d12bffce55c83b1bc63bb716d296**  
Latest release: **v0.1.0** (proof: `docs/proof/release-v0.1.0.md`)

### Phase 1 foundations (true in repo/tests)
- Deterministic scoring + tie-breakers
- Deterministic run report with schema version
- Input selection reason capture + replay tooling
- Snapshot-based offline determinism for providers
- Discord run summaries + diff-aware alerts
- Minimal dashboard API for runs/artifacts
- Weekly AI insights (guardrailed, cached), plus structured deterministic input artifacts
- Semantic “safety net” implemented with explicit mode split:
  - `SEMANTIC_MODE=sidecar|boost`
  - sidecar never mutates ranked outputs
- Deterministic cost accounting + budget guardrails (`costs.json`, token caps)
- Strong CI/Docker smoke gates with documented failure modes (`docs/CI_SMOKE_GATE.md`)

---

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

# NEW ROADMAP — Big Milestones (Phase 1.5 → Phase 2 foundations)

These milestones are intentionally **thicker**: each has real DoD, smaller sub-work items, and receipts.

## Milestone 10 — Provider Platform v1 (Config-Driven, Policy-Aware, Deterministic)

**Goal:** Adding providers is boring, safe, and consistent. Provider work is consolidated here.

### Definition of Done (DoD)
- Provider registry exists with a **versioned schema** (YAML/JSON):
  - `provider_id`, display name
  - careers URLs + allowed domains
  - extraction mode(s) (snapshot/live), cadence, and policy flags
  - robots/terms decision record (allow/deny/manual_review)
  - opt-out capability (provider tombstone)
- Provider addition requires **0–1 small code change** (ideally config-only).
- Extraction interface is stable + deterministic:
  - deterministic primary parse path (JSON-LD / structured HTML / API when available)
  - deterministic normalization (URL, locations, team/role family)
- Snapshot fixtures are first-class:
  - fixture pack includes index + per-job pages as needed
  - snapshot contract tests enforce fixture completeness for enabled providers
- Live scraping remains policy-aware + polite:
  - UA, rate limits, backoff, circuit breaker, deny-page detection remain enforced
  - provenance records policy decision and scrape_mode

### Work Items
- [ ] Define `provider_config.schema.json` (or equivalent) + loader + validation tests
- [ ] Move any “provider truth” that is still scattered into the registry
- [ ] Add “provider tombstone” record type + tests + behavior rules
- [ ] Add at least 3 providers beyond current set using registry (snapshot-first), with fixtures
- [ ] Expand provenance schema to include provider registry hash/version
- [ ] Docs: `docs/PROVIDERS.md` (how to add, policy rules, fixtures, receipts)

### Receipts Required
- Proof doc: `docs/proof/m10-provider-platform-v1-<date>.md`
- Tests proving: config validation, fixture completeness, deterministic ordering, deny/tombstone behavior

---

## Milestone 11 — Artifact Model v2 (Public UI-Safe vs Internal Replay-Safe)

**Goal:** Make legality + UX constraints enforceable via artifact design.

### Definition of Done (DoD)
- Artifacts are explicitly split into:
  - **UI-safe artifacts** (summaries, signals, diffs, links; no raw JD required)
  - **replay-safe artifacts** (archival inputs sufficient for reproducibility; access-controlled by deployment)
- UI-safe artifacts must be sufficient for dashboards and alerts:
  - canonical links, deltas, scoring explanation, top signals, status tags
- Replay-safe artifacts continue to support determinism:
  - hash verification, recalc diff, provenance
- Redaction/hygiene policy applies to replay-safe artifacts:
  - scanning + optional enforcement remains stable
- Retention policy differentiates UI-safe vs replay-safe (future-proof for multi-user)

### Work Items
- [ ] Define `docs/ARTIFACTS.md` with artifact taxonomy and “public vs internal” rules
- [ ] Implement UI-safe “job card” JSON artifact per run/profile:
  - minimal fields, canonical links, safe snippet policy
- [ ] Ensure Discord alerts and dashboard endpoints can run entirely from UI-safe artifacts
- [ ] Add tests: UI-safe artifacts contain no banned raw fields (policy enforced)
- [ ] Update dashboard endpoints to prefer UI-safe artifacts by default

### Receipts Required
- Proof doc: `docs/proof/m11-artifact-model-v2-<date>.md`
- Tests enforcing “UI-safe has no raw JD” (or explicit bounded snippets if chosen)

---

## Milestone 12 — Operations Hardening Pack (Run Reliability + Observability + Guardrails)

**Goal:** “No babysitting.” When it fails, it fails loudly and explainably.

### Definition of Done (DoD)
- Every run produces:
  - run report + costs + provenance + UI-safe artifacts
  - explicit failure stage and reason on error
- Operational visibility:
  - local: one command to inspect last run (fast)
  - cloud/k8s: log pointers + run_id discovery documented and reliable
- Guardrails enforced:
  - AI token caps + embeddings caps fail-closed (already exists; must remain wired everywhere)
  - provider circuit breaker behavior documented + verifiable in artifacts
- CI smoke gate is comprehensive and aligned with real run shape.

### Work Items
- [ ] Consolidate run inspection tooling: `scripts/ops/inspect_last_run.py` (or equivalent)
- [ ] Add `docs/FAILURE_PLAYBOOK.md` keyed by `failed_stage`
- [ ] Add CloudWatch/cluster logging “minimum viable” checklist with receipts (even if optional)
- [ ] Add “provider availability dashboard summary” artifact per run
- [ ] Ensure `docs/CI_SMOKE_GATE.md` is always current with workflows

### Receipts Required
- Proof doc: `docs/proof/m12-ops-hardening-<date>.md`
- Evidence artifacts from a forced provider failure scenario (offline deterministic simulation)

---

## Milestone 13 — AI Insights v1 (Actually Useful Weekly Intelligence)

**Goal:** Weekly insights are not vibes. They are grounded, actionable, and safe.

### Definition of Done (DoD)
- Weekly insights uses **structured deterministic input** (already underway) and improves usefulness:
  - diff trends (7/14/30 window)
  - role family and seniority shifts
  - location/remote trends
  - recurring skill tokens and “missing skills” signals derived from structured fields
- Output includes:
  - summary (Discord-safe)
  - full report markdown (artifact)
  - JSON schema output (artifact)
  - metadata containing cache keys + input hashes + prompt version
- Strict guardrails:
  - deterministic settings
  - schema validation
  - fail-closed on parse errors
  - cache keyed on run+inputs+prompt version
  - explicit “no raw JD leakage” contract

### Work Items
- [ ] Define `ai_weekly_insights.schema.json`
- [ ] Add “evidence appendix” section in markdown output referencing which structured fields drove claims
- [ ] Add a “top 5 actions this week” section tied to trends
- [ ] Tests: cache key correctness, schema validation, privacy/no leakage

### Receipts Required
- Proof doc: `docs/proof/m13-ai-insights-v1-<date>.md`
- Two-run comparison proof showing deterministic output changes when inputs change

---

## Milestone 14 — AI Per-Job Briefs v1 (Profile-Aware, Guardrailed, Cached)

**Goal:** Make the system feel like a coach *per job*, without turning into a hallucination generator.

### Definition of Done (DoD)
- For shortlisted jobs, generate a per-job brief:
  - why it matches (grounded in scoring signals)
  - likely interview focus areas (bounded claims)
  - “resume bullet suggestions” (based on candidate profile + job signals)
  - questions to ask / red flags
- Guardrails:
  - deterministic settings
  - strict schema output
  - caching keyed by job_id + job_hash + profile_hash + prompt_version
  - fail-closed (no “best effort” garbage)
- Legal/UI-safe:
  - briefs reference source links; do not replace full JD browsing

### Work Items
- [ ] Candidate profile hash contract (even before multi-user)
- [ ] `ai_job_brief.schema.json` + prompt template v1
- [ ] Pipeline step: generate briefs for top N (bounded, cost-controlled)
- [ ] Add cost accounting integration (brief tokens counted)
- [ ] Add artifacts:
  - `state/runs/<run_id>/ai/job_briefs/<job_id>.json`
  - optional markdown render

### Receipts Required
- Proof doc: `docs/proof/m14-ai-job-briefs-v1-<date>.md`
- Determinism proof: same inputs produce identical brief output hashes

---

## Milestone 15 — Explainability v1 (Score Reasons Users Can Trust)

**Goal:** Make “why this scored high” transparent and stable.

### Definition of Done (DoD)
- Each job in UI-safe artifacts includes:
  - top contributing signals (deterministic)
  - penalties/filters applied (deterministic)
  - semantic contribution (if enabled) bounded and visible
  - user state suppression reason (if applicable)
- Explanation format is stable and test-backed.

### Work Items
- [ ] Add `explanation_v1` structure to UI-safe job cards
- [ ] Tests for stable ordering and stable wording keys (no random dict order)
- [ ] Docs: `docs/EXPLAINABILITY.md`

### Receipts Required
- Proof doc + snapshot of artifacts showing explanation fields

---

## Milestone 16 — Dashboard Plumbing v2 (API First, UI Later)

**Goal:** Rock-solid backend surfaces so UI later is easy.

### Definition of Done (DoD)
- Dashboard API supports:
  - listing runs with pagination + filters (provider/profile/date)
  - fetching UI-safe artifacts efficiently
  - downloading replay-safe artifacts only via explicit endpoints (deployment-dependent)
  - basic “health + version + schema versions” endpoint
- Dependency model remains clean:
  - core install works without dashboard deps
  - dashboard extras are explicit
- CI verifies dashboard contract (warn-only okay if optional deps absent, but contract tests exist).

### Work Items
- [ ] Add `/version` endpoint exposing build metadata + schema versions
- [ ] Add `/runs/latest` and `/runs/<run_id>/profiles` helpers for UI simplicity
- [ ] Add “artifact index” endpoint that lists available artifacts by type (ui_safe, replay_safe)
- [ ] Document API contract in `docs/API.md`

### Receipts Required
- Proof doc demonstrating API can power a basic UI without touching internals

---

## Milestone 17 — Release Discipline v1 (Predictable, CLI-First)

**Goal:** Releases become boring proof points.

### Definition of Done (DoD)
- Release process documented and enforced:
  - changelog updated
  - tags signed/annotated
  - GitHub release created
  - proof doc created for each release
- Release gate checklist exists and is used.

### Work Items
- [ ] Add `docs/RELEASE_CHECKLIST.md` (preflight, CI green, smoke proof, receipts)
- [ ] Add `scripts/ops/release_preflight.py` (optional helper; deterministic checks only)
- [ ] Ensure `CHANGELOG.md` stays current and meaningful

### Receipts Required
- Each release has `docs/proof/release-vX.Y.Z.md` and references the SHA/tag

---

## Milestone 18 — On-Prem Execution Proof (k3s receipts, hardware-dependent)

**Goal:** Prove on-prem is stable and boring once hardware is ready.

### Definition of Done (DoD)
- k3s cluster runs stable for 72h with receipts:
  - node readiness stable
  - time sync verified
  - storage on USB (not SD)
- SignalCraft CronJob runs daily on-prem with stable artifacts
- Backup runs on schedule (on-prem → S3) and restore rehearsal repeats

### Work Items
- [ ] Add `docs/proof/m18-onprem-72h-<date>.md` with logs and metrics snapshots
- [ ] Add “one-command prove-it” wrapper for on-prem path (or documented manual sequence)

---

## Milestone 19 — Compliance/Policy Review Pack (Legality + Safety + Data Hygiene)

**Goal:** Turn “we believe it’s fine” into enforceable constraints + documentation.

### Definition of Done (DoD)
- Written policy docs exist and match implementation:
  - discovery net principle
  - content handling rules (UI-safe vs replay-safe)
  - provider policy decisions and opt-out
  - retention and deletion strategy
- “Security review” checklist exists (multi-model review acceptable):
  - secrets handling
  - dependency risk
  - artifact exposure risk
  - injection and prompt-safety boundaries
- Automated checks exist for high-risk regressions:
  - redaction enforcement option
  - no-raw-JD leakage in UI-safe artifacts
  - provider allowlist compliance

### Work Items
- [ ] Add `docs/POLICY_LEGALITY.md`
- [ ] Add `docs/SECURITY_REVIEW_CHECKLIST.md`
- [ ] Add a lightweight “policy gate” test suite (fast, deterministic)

---

## Milestone 20 — “Phase 2 Launchpad” (Plumbing for multi-user + real UI without building it yet)

**Goal:** Create the foundation so Phase 2 feels like assembly, not archaeology.

### Definition of Done (DoD)
- Candidate/profile identity model exists (even if single-user in practice):
  - `candidate_id` + profile config paths
  - run registry and user_state are ready for isolation
- Object-store key structure supports multi-user later (namespaced)
- API surfaces are compatible with a future UI auth boundary (even if auth not implemented yet).

### Work Items
- [ ] Define `candidate_profile.schema.json` + versioning
- [ ] Update run registry to include candidate_id (default `local-default`)
- [ ] Namespaced artifact paths (no breaking changes; compatibility layer)

---

# Phase 3 Preview — Milestones 21–30 (Big Product Moves)

These are intentionally preview-level. We flesh them into full DoD when Phase 2 begins.

21) **Multi-user + Auth v1** (basic practical auth, isolation enforced)  
22) **Resume/LinkedIn ingestion v1** (PDF/DOCX/text; schema’d; deterministic parsing pipeline)  
23) **Real UI v1** (search/filter/actions; job lifecycle; explainability in UI)  
24) **AI coaching v1** (weekly plan personalized; learning roadmap; portfolio suggestions)  
25) **AI outreach v1** (message drafts; networking sequences; guarded and optional)  
26) **Advanced analytics v1** (trends across providers; time series; dedupe stability)  
27) **Alternative alerts** (email, push, RSS; rate-limited; preferences)  
28) **Provider scale pack** (more providers, anti-bot resiliency, legal/policy enforcement tooling)  
29) **Cost optimization pack** (S3 caches, sampling, batch strategies, budget dashboards)  
30) **Code bloat review + architecture cleanup** (intentional pruning, module boundaries, doc alignment)

---

## “How many milestones should we do?”

**More than 10 is correct**, but not as “50 tiny milestones.”  
The plan above gives you:
- **10 thick milestones** (10–20) that could easily carry the project through the next major phase,
- plus a **preview of 21–30** so the long-term product arc stays coherent.

That keeps the “big milestone energy” while still allowing careful sub-work inside each.

---

## Notes / Reminders

- Keep legality constraints enforced by artifact/UI design (Milestone 11 + 19).
- Keep UI work focused on plumbing until Phase 3.
- Keep AI work aggressively guardrailed and grounded in artifacts (Milestones 13–15).
- Keep on-prem timing aligned to hardware availability (Milestones 18+).
