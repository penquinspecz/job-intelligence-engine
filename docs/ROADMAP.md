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

---

## Current State (as of this commit)

Completed foundation (verified in repo/tests):
- [x] Deterministic ranking + tie-breakers
- [x] `--prefer_ai` is opt-in; no implicit AI switching
- [x] Short-circuit reruns scoring if ranked artifacts missing
- [x] `--no_enrich` input selection guarded by freshness (prefer enriched only when newer)
- [x] Strong regression coverage across scoring paths + short-circuit behavior
- [x] Docker build runs tests; docker smoke run validated in CI
- [x] Repo-root path safety: config no longer depends on CWD (`REPO_ROOT` anchored to `__file__`)
- [x] Run metadata now includes inputs + scoring inputs by profile + output hashes
- [x] Run report schema version is written and asserted in tests
- [x] Exit codes normalized to policy: `0` success, `2` validation/missing inputs, `>=3` runtime/provider failures
- [x] Job identity URLs normalized (query/fragment stripped; stable casing/trailing slash)

New conventions added (scaffold only; no behavioral integration yet):
- [x] `state/user_state/` convention + loader utility returning `{}` if missing

Known sharp edges / TODO:
- [ ] Decide final canonical run-report location/name (`state/runs/` vs `state/run_reports/`) and standardize docs/tests
- [ ] Better provider failure surfacing (retries/backoff, explicit unavailable reasons)
- [ ] Log destination / rotation strategy (launchd/stdout/sink)
- [ ] “Replay a run” workflow from run report (determinism contract)

---

## Milestone 1 — Daily run is deterministic & debuggable (Local + Docker + CI)

**Goal:** “Boring daily.” If something changes, we know *exactly* why.

### Definition of Done (DoD)
- [x] `pytest -q` passes locally and in CI
- [x] Docker smoke run produces ranked outputs for at least one profile
- [x] A single JSON run report is written every run (counts, hashes, selected inputs, output hashes)
- [x] Clear exit codes:
  - `0` success
  - `2` missing required inputs / validation error
  - `>=3` runtime/provider failures
- [x] Docs: “How to run / How to debug / What files to inspect”

### Work Items
- [x] Add `docs/OPERATIONS.md` describing:
  - input selection rules (labeled vs enriched vs AI)
  - flags: `--no_enrich`, `--ai`, `--ai_only`, `--prefer_ai`
  - common failure modes + where artifacts live
- [x] Run report includes: run_id, git_sha/image_tag (best-effort), timings, counts per stage,
      selected input paths + mtimes + hashes, output hashes
- [x] CI docker smoke test asserts ranked artifacts + run report exists

---

## Milestone 1.5 — Determinism Contract & Replayability (Local Truth > Vibes)

**Goal:** Given a run report, you can reproduce and explain the output.

### Definition of Done (DoD)
- [ ] Run report clearly records *why* each scoring input was selected (rule + freshness comparison),
      not just which file was used.
- [ ] Run report has a stable schema contract:
  - [x] `run_report_schema_version` exists
  - [ ] Schema is documented in `docs/OPERATIONS.md` (or `docs/RUN_REPORT.md`) with field meanings
- [ ] “Replay a run” instructions exist:
  - given a run_id (and/or archived history dir), reproduce the exact shortlist output
- [ ] Optional but recommended: a small helper script `scripts/replay_run.py` that validates hashes
      and prints a clear “this run is reproducible / not reproducible” report.

### Work Items
- [ ] Add `selection_reason` fields in run report for:
  - labeled vs enriched resolution
  - enriched vs AI-enriched resolution (when applicable)
- [ ] Add `docs/RUN_REPORT.md` with schema and troubleshooting
- [ ] Add `scripts/replay_run.py` (non-invasive; read-only) + tests

---

## Milestone 2 — Deployment: scheduled run + S3 artifact publishing

**Goal:** “It runs itself.” EventBridge/ECS runs daily, pushes outputs, optional alert.

### Definition of Done (DoD)
- [ ] ECS task runs end-to-end with mounted/ephemeral state
- [ ] Artifacts uploaded to S3 with stable keys (per profile + latest + run_id)
- [ ] Optional Discord alert only when diffs exist (already gated)
- [ ] Minimal IAM policy documented (least privilege)
- [ ] Runbook: how to redeploy, how to inspect last run, how to roll back

### Work Items
- [ ] Finalize `scripts/publish_s3.py` + `scripts/report_changes.py` usage in pipeline
- [ ] Add/complete `ops/aws/README.md` with:
  - required env vars/secrets
  - ECS taskdef + EventBridge rule wiring steps
  - artifact key structure and retention policy

---

## Milestone 2.5 — Provider Expansion (Safe, Config-Driven, Deterministic)

**Goal:** Add multiple AI companies without turning this into a scraper-maintenance job.

**Core rule:** no “LLM as scraper” unless it is cached, schema-validated, deterministic, and fail-closed.

### Definition of Done (DoD)
- [ ] Provider registry supports adding a new company via configuration:
  - name, careers URL(s), extraction mode, allowed domains, update cadence
- [ ] Extraction has a deterministic primary path (API/structured HTML/JSON-LD) when possible
- [ ] Optional LLM fallback extraction exists *only* with guardrails:
  - temperature 0, strict JSON schema, parse+validate, cache keyed by page hash,
    and “unavailable” on parse failures (no best-effort junk)
- [ ] A new provider can be added with ≤1 small code change (ideally none) + a config entry.

### Work Items
- [ ] Define provider config schema (YAML/JSON) and loader
- [ ] Implement a “safe extraction” interface:
  - `extract_jobs(html) -> List[JobStub]` with deterministic outputs
- [ ] Add at least 2 additional AI companies using the config mechanism (proof of ROI)

---

## Milestone 3 — History & intelligence (job identity, dedupe, trend reporting + user state)

**Goal:** track jobs across time, reduce noise, and make changes meaningful.

### Definition of Done (DoD)
- [ ] `job_identity()` produces stable IDs across runs for the same posting
  - [x] URL normalization reduces false deltas (query/fragment stripped)
  - [ ] Remaining stability work: canonicalization rules for common URL variants
- [ ] Dedupe collapse: same job across multiple listings/URLs → one canonical record
- [ ] “Changes since last run” uses identity-based diffing (not just row diffs)
- [ ] History directory grows predictably without exploding (retention rules)
- [ ] **User State overlay** exists (candidate actions):
  - applied / ignore / interviewing / saved, etc.
  - output markdown + alerts respect this state (filter or annotate)

### Work Items
- [ ] Implement/validate identity strategy (title/location/team + URL + jd hash fallback)
- [ ] Store per-run identity map + provenance in `state/history/<profile>/...`
- [ ] Add “new/changed/removed” driven by identity diff
- [ ] Implement `state/user_state/<profile>.json` overlay:
  - schema: `{ "<job_id>": { "status": "...", "date": "...", "notes": "..." } }`
  - integrate into shortlist writer and alerting
- [ ] Retention policy (keep last N runs + daily snapshots) documented and enforced

---

## Milestone 3.5 — Semantic Safety Net (Deterministic Discovery)

**Goal:** Catch “good fits with weird wording” without losing explainability.

**Rule:** Semantic similarity is a bounded booster / classifier safety net, not a replacement for explainable rules.

### Definition of Done (DoD)
- [ ] Deterministic embedding path (fixed model + stable text normalization)
- [ ] Similarity used as:
  - a minimum relevance floor (e.g., promote to RELEVANT if above threshold), and/or
  - a bounded score adjustment
- [ ] Thresholds are testable + documented
- [ ] Artifacts include similarity evidence for explainability

### Work Items
- [ ] Add embedding cache + cost controls (max jobs embedded per run)
- [ ] Add tests for deterministic similarity behavior and threshold boundaries

---

## Milestone 4 — Hardening & scaling (providers, cost controls, observability)

**Goal:** resilient providers, predictable cost, better monitoring.

### Definition of Done (DoD)
- [ ] Provider layer supports retries/backoff + explicit unavailable reasons
- [ ] Rate limiting / quota controls enforced
- [ ] Observability: CloudWatch metrics/alarms (or equivalent) + run dashboards
- [ ] Optional caching backend (S3 cache for AI outputs/embeddings)
- [ ] Log sink + rotation strategy documented

### Work Items
- [ ] Provider abstraction (Ashby + future providers) with snapshot/live toggles
- [ ] Cost controls: sampling, max jobs enriched, max AI tokens per run
- [ ] Log sink + rotation strategy documented

---

## Non-goals (for now)

- UI/dashboard until Milestone 2 is solid
- Multi-provider expansion until identity + history are stable (except Milestone 2.5 safety work)
- Large refactors unless they directly unlock a DoD checkbox

---

## Backlog Parking Lot (ideas that can wait)

- Dashboard/alerts enhancements (filters, structured payloads)
- Multiple candidate profiles / multi-target scoring
- Fancy AI insights (summaries, suggested outreach, skill gap analysis)
