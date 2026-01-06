# Misc & Docs
Included: `README.md`, `docs/ARCH_REVIEW_GEMINI.md` (status doc). Why: top-level description and architecture review context.

Omitted: none (full contents below).

## README.md
```
# Job Intelligence Engine (JIE)

An AI-powered job intelligence system that monitors frontier AI company careers pages, classifies roles, matches them to a candidate profile, and generates insights and alerts.

## Status

Early development. Architecture and project plan in progress.

## Goals

- Continuously scrape OpenAI careers (later: Anthropic, Google, etc.)
- Classify roles by function (Solutions Architecture, AI Deployment, CS, etc.)
- Compute a fit score and gap analysis against a structured candidate profile
- Generate weekly hiring trend summaries and real-time alerts for high-fit roles
- Demonstrate practical use of LLMs, embeddings, and workflow automation

## Architecture

High level:

- Provider-agnostic scraper layer  
- Embedding + classification pipeline (OpenAI API)  
- Matching engine (fit + gaps)  
- Insight generator (weekly / monthly pulse)  
- Notification & dashboard layer  

## AI-Assisted Development

This project is intentionally built using AI pair programming:

GPT-5 is used for design, code generation, and refactoring.

A second model (e.g. Gemini) is used as a cross-model reviewer for critical modules (scraper, matching engine, etc.).

The goal is to demonstrate practical, safe use of multi-model workflows for software engineering.

## Local setup (editable install)

```bash
python -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e .
# Example run (no Discord post):
python scripts/run_daily.py --profiles cs --us_only --no_post
```

## Roadmap

Sprint 0: Repo setup, models, and basic scraper skeleton

Sprint 1: Raw scraping of OpenAI careers → JSON

Sprint 2: Embeddings + basic classification

Sprint 3: Matching engine + Discord alerts

Sprint 4: Insights + Streamlit dashboard

Sprint 5: Add additional providers (Anthropic, etc.)
```

## docs/ARCH_REVIEW_GEMINI.md
```
# Architecture Review (Gemini) – Implementation Status (as of 2026-01-06)

This document tracks Gemini’s recommendations and architecture-area critiques.
Legend:
- ✅ DONE = implemented and verified locally
- 🧭 DEFERRED = intentionally planned, not implemented yet
- ⏳ PARTIAL = started / mitigated, but not fully completed
- ❌ NOT DONE = not addressed yet

---

## Recommendations (Top 10 Refactors – Ranked by ROI)

1) **Add “On Failure” Alerting (High ROI)**  
- Status: ✅ DONE  
- What changed: `scripts/run_daily.py` posts a Discord failure alert with stage context + error summary; honors `--no_post`.  
- Files: `scripts/run_daily.py`  
- Verify: `python scripts/run_daily.py --profiles cs --us_only --no_post` (force failure by temporarily renaming a stage script)

2) **Delete _bootstrap.py / Fix Imports (High ROI)**  
- Status: ✅ DONE  
- What changed: Removed `sys.path.insert` hacks; added editable install workflow; scripts import `ji_engine` normally.  
- Files: `scripts/_bootstrap.py` (deleted), `README.md`, various `scripts/*.py` imports  
- Verify: `pip install -e .` and `python -c "import ji_engine; print('ok')"`

3) **Centralize File Paths (Medium ROI)**  
- Status: ✅ DONE  
- What changed: Centralized pipeline paths in `src/ji_engine/config.py`; scripts consume config helpers instead of hardcoded `data/...` strings.  
- Files: `src/ji_engine/config.py`, `scripts/enrich_jobs.py`, `scripts/score_jobs.py`, `scripts/run_daily.py`, etc.  
- Verify: `python scripts/run_daily.py --profiles cs,tam,se --us_only --no_post`

4) **Containerize (Medium ROI)**  
- Status: 🧭 DEFERRED  
- Rationale: Intentionally postponed until pipeline stability + packaging baseline locked in.  
- Planned deliverables: `Dockerfile`, `compose.yaml` (optional), volume mount for `./data`, env for webhook.  
- Verify (when done): `docker build .` and run daily inside container with `./data` mounted.

5) **Refactor run_daily.py to Library Calls vs subprocess (Medium ROI)**  
- Status: 🧭 DEFERRED  
- Rationale: Subprocess orchestration is currently intentional for isolation; refactor planned after containerization.  
- Planned approach: introduce `src/ji_engine/pipeline/` modules and call them directly, or keep subprocess but unify args + paths.

6) **Snapshot Testing / Golden Master (Medium ROI)**  
- Status: ✅ DONE (scoring golden master)  
- What changed: Added a golden-master test ensuring scoring stability (counts + top-10 titles + scores).  
- Files: `tests/test_score_jobs_golden_master.py`, `tests/fixtures/openai_enriched_jobs.sample.json`  
- Verify: `pytest -q`

7) **Structured Logging (Low ROI)**  
- Status: ✅ DONE  
- What changed: Replaced prints with `logging` across pipeline scripts; preserved message content; structured timestamps/levels.  
- Files: `scripts/run_daily.py`, `scripts/run_scrape.py`, `scripts/run_classify.py`, `scripts/enrich_jobs.py`, `scripts/score_jobs.py`  
- Verify: run pipeline and confirm logs show timestamps/levels.

8) **Pydantic for Everything (Low ROI)**  
- Status: 🧭 DEFERRED  
- Rationale: Not currently needed; would be a larger structural change.  
- Potential future: retain typed objects longer to catch schema drift earlier.

9) **Remove HTML_TO_TEXT Regex (Low ROI)**  
- Status: ✅ DONE  
- What changed: Standardized HTML → text extraction using BeautifulSoup.get_text() with normalization.  
- Files: `src/ji_engine/integrations/html_to_text.py`
- Verify: `python -m scripts.enrich_jobs` and confirm enriched/unavailable counts unchanged.

10) **Dynamic User-Agent (Low ROI)**  
- Status: 🧭 DEFERRED  
- Rationale: Not required given current snapshot fallback; revisit if live scraping reliability becomes priority.

---

## Architecture Areas (5)

1) **Architecture Critique: Modular but “Script-Bound” (subprocess runner / filesystem side effects)**  
- Status: ⏳ PARTIAL  
- Mitigation done: Paths centralized (single config source); better logging; failure alerting; tests added.  
- Still true: subprocess orchestration and file-based handoffs remain by design.  
- Planned: pipeline library refactor after Docker.

2) **Reliability Risks: Silent failures / brittle parsing assumptions**  
- Status: ⏳ PARTIAL  
- DONE: Failure alerts with stage context; logging; HTML-to-text robustness improved.  
- Remaining: strengthen “treat 400/500 as unavailable” guarantees in Ashby integration; add retry/backoff guardrails if needed.

3) **Security & Privacy: public data, webhook hygiene, dependency/path risks**  
- Status: ✅ DONE (for cited issues)  
- DONE: Removed path-hack imports; webhook env usage already good.  
- Remaining: optional UA rotation (deferred); review any remaining hardcoded headers.

4) **Packaging & Deploy Path: launchd brittleness / need containerization**  
- Status: ⏳ PARTIAL  
- DONE: Editable install documented; config centralization reduces cwd sensitivity.  
- Remaining: Docker containerization (deferred).

5) **Test Strategy: unit tests exist, integration missing**  
- Status: ⏳ PARTIAL  
- DONE: scoring golden master test.  
- Remaining: full-pipeline golden master using snapshot HTML → ranked outputs.
```

