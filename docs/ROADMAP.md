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

---

## Current State (as of last commit)

Completed foundation:
- Deterministic ranking + tie-breakers
- `--prefer_ai` is opt-in; no implicit AI switching
- Short-circuit reruns scoring if ranked artifacts missing
- `--no_enrich` input selection guarded by freshness (prefer enriched only when newer)
- Strong regression coverage across scoring paths + short-circuit behavior
- Docker build runs tests; local runs validated

Known sharp edges / TODO:
- Better provider failure surfacing (retries/backoff, explicit unavailable)
- Log destination / rotation strategy (launchd/stdout/sink)

---

## Milestone 1 — Daily run is deterministic & debuggable (Local + Docker + CI)

**Goal:** “Boring daily.” If something changes, we know *exactly* why.

### Definition of Done (DoD)
- [ ] `make test` (or `pytest -q`) passes locally and in CI
- [ ] Docker smoke run produces ranked outputs for at least one profile
- [ ] A single JSON run report is written every run (counts, hashes, selected inputs)
- [ ] Clear exit codes:
  - `0` success
  - `2` missing required inputs / validation error
  - `>=3` runtime/provider failures
- [ ] Docs: “How to run / How to debug / What files to inspect”

### Work Items
- [ ] Add `docs/OPERATIONS.md` (or a README section) describing:
  - input selection rules (labeled vs enriched vs AI)
  - flags: `--no_enrich`, `--ai`, `--ai_only`, `--prefer_ai`
  - common failure modes + where artifacts live
- [ ] Run report: `state/run_reports/<timestamp>.<run_id>.json`
  - includes: run_id, git_sha/image_tag, timings, counts per stage, selected input paths + mtimes + hashes, output hashes
- [ ] CI docker smoke test (tmp data/state mounts) asserts:
  - ranked JSON/CSV/MD exists
  - run report exists

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
- [ ] Add `ops/aws/README.md` with:
  - required env vars/secrets
  - ECS taskdef + EventBridge rule wiring steps
  - artifact key structure and retention policy

---

## Milestone 3 — History & intelligence (job identity, dedupe, trend reporting)

**Goal:** track jobs across time, reduce noise, and make changes meaningful.

### Definition of Done (DoD)
- [ ] `job_identity()` produces stable IDs across runs for the same posting
- [ ] Dedupe collapse: same job across multiple listings/URLs → one canonical record
- [ ] “Changes since last run” uses identity-based diffing (not just row diffs)
- [ ] History directory grows predictably without exploding (retention rules)

### Work Items
- [ ] Implement + validate `job_identity()` (title/location/team + URL + jd hash)
- [ ] Store per-run identity map + provenance in `state/history/<profile>/...`
- [ ] Add “new/changed/removed” driven by identity diff
- [ ] Optional: job family grouping stabilized (if not already)

---

## Milestone 4 — Hardening & scaling (providers, cost controls, observability)

**Goal:** resilient providers, predictable cost, better monitoring.

### Definition of Done (DoD)
- [ ] Provider layer supports retries/backoff + explicit unavailable reasons
- [ ] Rate limiting / quota controls enforced
- [ ] Observability: CloudWatch metrics/alarms (or equivalent) + run dashboards
- [ ] Optional caching backend (S3 cache for AI outputs/embeddings)

### Work Items
- [ ] Provider abstraction (Ashby + future providers) with snapshot/live toggles
- [ ] Cost controls: sampling, max jobs enriched, max AI tokens per run
- [ ] Log sink + rotation strategy documented

---

## Non-goals (for now)

- UI/dashboard until Milestone 2 is solid
- Multi-provider expansion until identity + history are stable
- Large refactors unless they directly unlock a DoD checkbox

---

## Backlog Parking Lot (ideas that can wait)

- Dashboard/alerts enhancements (filters, structured payloads)
- Multiple candidate profiles / multi-target scoring
- Fancy AI insights (summaries, suggested outreach, skill gap analysis)