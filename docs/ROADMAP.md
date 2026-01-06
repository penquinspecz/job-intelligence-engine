# Roadmap (Gemini-aligned)

## Phased Plan
- **Phase 0: Stabilize**
  - Entry: Current state.
  - Exit: Reliable daily run with failure alerts, structured logs, golden-master scoring, deterministic HTML-to-text, absolute paths, ensure_dirs, atomic writes, Ashby null-guard.
- **Phase 1: Deploy**
  - Entry: Phase 0 exit met.
  - Exit: Containerized run, clean config/env handling, optional launchd/cron setup with clear logs, path-free dependencies.
- **Phase 2: “True AI”**
  - Entry: Phase 1 exit met.
  - Exit: Additional providers, smarter scoring/ML, AI-assisted insights; full integration test coverage.

## Reliability & Observability
- [x] Structured logging across pipeline (INFO, timestamp/level).  
  - Files: `scripts/run_daily.py`, `scripts/run_scrape.py`, `scripts/run_classify.py`, `scripts/enrich_jobs.py`, `scripts/score_jobs.py`  
  - Verify: `python scripts/run_daily.py --profiles cs --us_only --no_post`
- [x] Failure alerts include stderr/stdout tails (Discord payload).  
  - Files: `scripts/run_daily.py`  
  - Verify: temporarily break a stage (rename a script), run `python scripts/run_daily.py --profiles cs --us_only --no_post`
- [x] Absolute stage paths + cwd=REPO_ROOT for subprocesses.  
  - Files: `scripts/run_daily.py`, `src/ji_engine/config.py`  
  - Verify: `python scripts/run_daily.py --profiles cs --us_only --no_post`
- [x] ensure_dirs() at startup to create data/state/snapshot/cache.  
  - Files: `src/ji_engine/config.py`, `scripts/run_daily.py`  
  - Verify: `python - <<'PY'\nfrom ji_engine.config import ensure_dirs; ensure_dirs(); print('ok')\nPY`
- [x] Atomic writes (Ashby cache, enriched JSON, ranked JSON/CSV/families, shortlist MD).  
  - Files: `src/ji_engine/utils/atomic_write.py`, `src/ji_engine/integrations/ashby_graphql.py`, `scripts/enrich_jobs.py`, `scripts/score_jobs.py`  
  - Verify: `python -m py_compile ...` and run daily; inspect outputs exist and are not partial.
- [x] GraphQL null jobPosting guard (treat as unavailable, do not cache) + test.  
  - Files: `src/ji_engine/integrations/ashby_graphql.py`, `tests/test_ashby_graphql_null_jobposting.py`  
  - Verify: `pytest -q`
- [ ] Broader failure surfacing in integrations (e.g., Ashby fetch retries / explicit unavailable on 4xx/5xx).  
  - Files: `scripts/enrich_jobs.py`, `src/ji_engine/integrations/ashby_graphql.py`  
  - Verify: simulated 4xx/5xx still completes with marked unavailable.
- [ ] Log rotation / destination strategy (launchd/stdout).  
  - Files: launchd plist, docs  
  - Verify: logs rotate or ship to desired sink.

## Portability & Deploy
- [x] Absolute script paths; no cwd reliance. (See Reliability)  
- [ ] Containerize pipeline (Dockerfile + volume for ./data).  
  - Files: `Dockerfile`, `Makefile`, docs  
  - Verify: `docker build .`, `docker run --rm -v "$PWD/data:/app/data" ...`
- [ ] Canonical code location cleanup: integrations live in `src/ji_engine/integrations/`; remove legacy shims.  
  - Files: `src/ji_engine/integrations/*`  
  - Verify: imports resolve without scripts/*; delete duplicates after switch.
- [ ] Script sprawl cleanup; clarify single entrypoint (`scripts/run_daily.py`); mark/deprecate old runners.  
  - Files: `scripts/run_openai_pipeline.py`, `scripts/run_full_pipeline.py`, docs/ROADMAP  
  - Verify: docs updated; deprecated scripts either removed or clearly marked.

## Data Integrity
- [x] Centralized paths in config; ensure_dirs.  
  - Files: `src/ji_engine/config.py`, pipeline scripts  
  - Verify: `python -m py_compile src/ji_engine/config.py`
- [x] Atomic writes for key outputs (see Reliability).  
- [ ] Add hash/diff checks for inputs/outputs (optional).  
  - Files: `scripts/run_daily.py`, potential helper  
  - Verify: compare hashes before/after run.

## Performance
- [ ] None targeted yet (IO-bound pipeline). Keep snapshot size manageable.  
  - Files: n/a  
  - Verify: runtime remains acceptable.

## Maintainability
- [x] BeautifulSoup HTML-to-text (no regex stripper).  
  - Files: `src/ji_engine/integrations/html_to_text.py`  
  - Verify: `python -m scripts.enrich_jobs`
- [x] Structured logging (see Reliability).  
- [ ] Move integrations fully into `src/ji_engine/integrations` (remove bridges); delete duplicate script versions after unification.  
  - Files: `src/ji_engine/integrations/ashby_graphql.py`  
  - Verify: imports resolve without `scripts.*`.
- [ ] Library-mode orchestration (reduce subprocess use) — deferred until after containerization.  
  - Files: `scripts/run_daily.py`, potential `src/ji_engine/pipeline/*`
- [ ] Scoring global state mutation refactor (hard/later) — avoid global ROLE_BAND/PROFILE_WEIGHTS mutation.  
  - Files: `scripts/score_jobs.py`  
  - Verify: idempotent runs, parallel safety.
- [ ] Log rotation / destination strategy (launchd/log files).  
  - Files: launchd plist, docs  
  - Verify: logs rotate or ship to desired sink.
- [ ] Fix “silent skip” tests: missing fixtures should explicit-skip with reason or fail.  
  - Files: `tests/test_openai_provider.py`, any fixture-dependent tests  
  - Verify: `pytest -q` shows explicit skip or passes.

## Tests
- [x] Golden master scoring test (stable top-10 titles/scores).  
  - Files: `tests/test_score_jobs_golden_master.py`, `tests/fixtures/openai_enriched_jobs.sample.json`  
  - Verify: `pytest -q`
- [x] GraphQL null jobPosting guard test.  
  - Files: `tests/test_ashby_graphql_null_jobposting.py`  
  - Verify: `pytest -q`
- [ ] Full-pipeline golden master (snapshot HTML -> ranked outputs).  
  - Files: tests + fixtures  
  - Verify: `pytest -q`
- [ ] Broader regression tests for enrichment failure modes.  
  - Files: `tests/`  
  - Verify: `pytest -q`
- [ ] Fix silent skips (make skips explicit with reason or fail).  
  - Files: `tests/` (e.g., provider snapshot dependencies)  
  - Verify: `pytest -q` shows explicit skip or pass.

## Gemini Review Items (All Chunks)
- [x] Docker + snapshot strategy (bake snapshots, expect /app/data mount).  
  - Phase: 1  
  - Why: offline/snapshot runs work in containers.  
  - Files: `Dockerfile`, `.dockerignore`, `README.md`  
  - Verify: `docker build -t jobintel:local .`; `docker run --rm jobintel:local --profiles cs --us_only --no_post`
- [x] Failure alerts with stderr/stdout tails.  
  - Phase: 0  
  - Why: faster incident triage.  
  - Files: `scripts/run_daily.py`  
  - Verify: force failure; observe logs and (if no_post false) Discord payload.
- [x] Absolute paths + cwd=REPO_ROOT.  
  - Phase: 0  
  - Why: portability, cron/launchd/container safety.  
  - Files: `scripts/run_daily.py`  
  - Verify: `python scripts/run_daily.py --profiles cs --us_only --no_post`
- [x] ensure_dirs() at startup.  
  - Phase: 0  
  - Why: prevent missing dirs in fresh envs.  
  - Files: `src/ji_engine/config.py`, `scripts/run_daily.py`  
  - Verify: `python - <<'PY'\nfrom ji_engine.config import ensure_dirs; ensure_dirs(); print('ok')\nPY`
- [x] Atomic writes (cache/enriched/ranked/families/shortlist).  
  - Phase: 0  
  - Why: avoid partial files on crash.  
  - Files: `src/ji_engine/utils/atomic_write.py`, `src/ji_engine/integrations/ashby_graphql.py`, `scripts/enrich_jobs.py`, `scripts/score_jobs.py`  
  - Verify: `python -m py_compile ...`; run daily.
- [x] GraphQL null jobPosting guard + test (no-cache on null).  
  - Phase: 0  
  - Why: avoid caching invalid responses; treat as unavailable.  
  - Files: `src/ji_engine/integrations/ashby_graphql.py`, `tests/test_ashby_graphql_null_jobposting.py`  
  - Verify: `pytest -q`
- [x] BeautifulSoup HTML-to-text.  
  - Phase: 0  
  - Why: deterministic HTML parsing; remove regex stripper.  
  - Files: `src/ji_engine/integrations/html_to_text.py`  
  - Verify: `python -m scripts.enrich_jobs`
- [x] Golden master scoring test.  
  - Phase: 0  
  - Why: guard scoring drift.  
  - Files: `tests/test_score_jobs_golden_master.py`, fixture  
  - Verify: `pytest -q`
- [ ] Script sprawl cleanup / single entrypoint (mark/deprecate legacy runners).  
  - Phase: 1  
  - Why: reduce confusion; one way to run.  
  - Files: `scripts/run_full_pipeline.py`, `scripts/run_openai_pipeline.py`, docs  
  - Verify: docs updated; deprecated scripts marked/removed.
- [ ] Remove split-brain duplicates (scripts/* shims -> src/* only).  
  - Phase: 1  
  - Why: single canonical integrations.  
  - Files: `src/ji_engine/integrations/*`  
  - Verify: imports resolve without scripts; delete shims.
- [ ] Logging destination/rotation strategy (stdout-first; launchd notes).  
  - Phase: 1  
  - Why: prevent log growth; route logs predictably.  
  - Files: `ops/launchd/*.plist`, docs  
  - Verify: logs rotate or ship to desired sink.
- [ ] Optional parallel enrichment (bounded concurrency).  
  - Phase: 2  
  - Why: speed up enrichment while respecting rate limits.  
  - Files: `scripts/enrich_jobs.py`, maybe asyncio/threading helper  
  - Verify: wall-clock improvement; no rate-limit regressions.
- [ ] Scoring global-state refactor (HARD/DEFER).  
  - Phase: 2  
  - Why: eliminate global mutations for parallel safety.  
  - Files: `scripts/score_jobs.py`  
  - Verify: idempotent/parallel runs unchanged.
- [ ] Fix silent-skip tests (explicit skip/fail if fixtures missing).  
  - Phase: 0  
  - Why: avoid false green.  
  - Files: `tests/` (provider snapshot-dependent tests)  
  - Verify: `pytest -q` shows explicit skips or passes.
- [ ] Full end-to-end pipeline golden master (snapshot HTML -> ranked outputs).  
  - Phase: 1  
  - Why: catch regressions across stages.  
  - Files: tests + fixtures  
  - Verify: `pytest -q`

## True AI Phase
- [ ] Add additional providers (Anthropic/others) with snapshot + live modes.  
  - Files: `src/ji_engine/providers/*`, `scripts/run_scrape.py`  
  - Verify: provider-specific tests, run_daily multi-provider.
- [ ] Smarter scoring/ML and insights.  
  - Files: `scripts/score_jobs.py`, `src/ji_engine/pipeline/*`  
  - Verify: updated golden masters + unit tests.
- [ ] Dashboard/alerts enhancements (structured payloads, filters).  
  - Files: `src/ji_engine/dashboard/*`, alerting hooks  
  - Verify: manual smoke + tests.

