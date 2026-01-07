## Model strategy (Cursor) — job-intelligence-engine

This repo benefits from **fast iteration for small changes** and **high-reliability reasoning** for pipeline orchestration, concurrency, and multi-file refactors. Use this playbook to choose the cheapest model that still keeps you safe.

### Default rule

Start with **GPT-5.1 Codex Mini** (or **Gemini 3 Flash** if you just need quick reading/summarization).  
Only “graduate” to larger models when the task **spans multiple files**, **touches `scripts/run_daily.py` orchestration**, **involves concurrency (e.g., `scripts/enrich_jobs.py`)**, or **requires a high-confidence design change**.

### Task type → recommended model (Cursor)

| Task type | Recommended model | Why |
|---|---|---|
| Single-file, small edit (docs, formatting, small bugfix) | **GPT-5.1 Codex Mini** | Fast, cheap, good at tactical diffs |
| Small-to-medium feature in one area (1–3 files) | **GPT-5.2** or **Sonnet 4.5** | Better system understanding, fewer integration mistakes |
| Multi-file refactor across pipeline stages | **GPT-5.1 Codex Max** | Best at dependency graph + safe mechanical edits |
| Concurrency changes / determinism / ordering | **GPT-5.1 Codex Max** (or **GPT-5.2**) | Stronger correctness + edge-case handling |
| Pipeline orchestration / stage short-circuiting / telemetry (`scripts/run_daily.py`) | **GPT-5.1 Codex Max** | Highest leverage area; regressions are costly |
| Test authoring / golden masters / fixtures | **GPT-5.2** or **GPT-5.1 Codex Mini** | Strong pytest instincts; keep diffs tight |
| Quick codebase survey / “where is X?” / rough plan | **Gemini 3 Flash** | Fast scanning and summarization |
| Large architectural review (pros/cons, roadmap) | **Opus 4.5** or **GPT-5.2** | Better long-form reasoning, risk analysis |
| “Second opinion” on tricky change | **Sonnet 4.5** (or **Opus 4.5**) | Useful cross-check for design mistakes |
| Niche/alt reasoning (style, unconventional approaches) | **Grok Code** | Sometimes finds different angles; verify carefully |

---

## Per-model guidance

### Opus 4.5

- **Best use-cases**
  - High-level architecture and roadmap docs (e.g., `docs/ROADMAP.md`, `docs/ARCH_REVIEW_GEMINI.md`)
  - Risk analysis and migration strategy for big changes (e.g., “subprocess vs library-mode pipeline”)
- **Common failure modes**
  - Over-designing (too many abstractions, too much ceremony)
  - Producing plausible but unverified repo details (hallucinated files/flags)
- **When NOT to use**
  - Tight, mechanical diffs (use Codex Mini)
  - Concurrency correctness patches where you need precise edits (use Codex Max / GPT-5.2)

### Sonnet 4.5

- **Best use-cases**
  - Implementation planning + medium-sized changes across a few files
  - Reviewing an existing PR/diff for pitfalls (especially around `run_daily.py` stage wiring)
- **Common failure modes**
  - “Looks right” patches that miss one import path, CLI flag, or test seam
  - Underestimating determinism constraints (ordering, stable fixtures)
- **When NOT to use**
  - Deep multi-file refactors with many moving parts (prefer Codex Max)
  - When you need exhaustive dependency scanning across `scripts/` + `src/ji_engine/`

### GPT-5.1 Codex Max

- **Best use-cases**
  - Multi-file refactors with strict correctness requirements
  - Pipeline orchestration changes in `scripts/run_daily.py` (stages, telemetry, hashing, short-circuiting)
  - Concurrency + determinism work (e.g., `scripts/enrich_jobs.py` ThreadPoolExecutor behavior)
  - Test harnesses that need isolation (tmp_path data roots, offline stubs, fixtures)
- **Common failure modes**
  - Can “go broad” and touch too many files if scope isn’t constrained
  - Might introduce large diffs when a smaller change would do
- **When NOT to use**
  - Simple docs edits
  - Small isolated fixes (start with Codex Mini)

### GPT-5.2

- **Best use-cases**
  - End-to-end reasoning across pipeline + tests, with good balance of speed and depth
  - Designing robust interfaces (e.g., provider abstractions, cache backends) with minimal overengineering
  - Debugging tricky failures where you need both reasoning and code edits
- **Common failure modes**
  - May propose “cleanups” that exceed the request if you don’t specify constraints
  - Can miss a subtle CLI/env interaction if not explicitly tested
- **When NOT to use**
  - Very large mechanical refactors (Codex Max is usually safer)
  - Quick scans/summaries (Gemini Flash is cheaper)

### Gemini 3 Flash

- **Best use-cases**
  - Fast repo exploration: “where is this used?” “what calls this?” “summarize this script”
  - Quick doc drafts and checklists
- **Common failure modes**
  - Shallow edits that compile but don’t meet repo invariants (determinism, tmp_path isolation)
  - Not great at long multi-file change execution without tight guidance
- **When NOT to use**
  - Anything touching `scripts/run_daily.py` stage orchestration or determinism guarantees
  - Concurrency changes (use Codex Max / GPT-5.2)

### GPT-5.1 Codex Mini

- **Best use-cases**
  - Small edits with high signal: adjust a flag, fix an import, add/patch a test
  - Tight diffs in one file (or a couple) where you know what you want
  - Incremental refactors that can be done safely in steps
- **Common failure modes**
  - May miss cross-file ripple effects unless you point it to related files
  - Less robust at “system-wide” reasoning (env/CLI + runtime interactions)
- **When NOT to use**
  - Multi-file refactors that require dependency scanning
  - Orchestration changes where one missed stage wire breaks the pipeline

### Grok Code

- **Best use-cases**
  - Alternative solution brainstorming
  - Spot-checking for edge cases or style/readability improvements
- **Common failure modes**
  - Inconsistent with repo conventions and test expectations
  - Higher chance of “creative” suggestions that aren’t warranted
- **When NOT to use**
  - Deterministic golden master updates and fixture generation (be conservative)
  - Concurrency correctness or stage orchestration work

---

## When to spend Codex Max (repo-specific)

Use **GPT-5.1 Codex Max** when the cost of a mistake is high or the change is inherently cross-cutting. Concrete examples in this repo:

1. **Multi-file refactor of data paths / env overrides**
   - Example: introducing `JOBINTEL_DATA_DIR` so `src/ji_engine/config.py`, `scripts/run_daily.py`, and tests all agree on where artifacts live.
   - Why Max: it’s easy to miss one “stringly-typed” path or a module import that freezes config at import-time.

2. **Tricky concurrency + determinism changes**
   - Example: modifying `scripts/enrich_jobs.py` parallel enrichment (ThreadPoolExecutor), ensuring deterministic output order and stable logs, and adding bounded flags for test speed.
   - Why Max: concurrency bugs are subtle; determinism regressions break golden tests and CI.

3. **Pipeline orchestration changes**
   - Example: adding telemetry, hash short-circuiting, stage skipping, or changing subprocess vs in-process execution in `scripts/run_daily.py`.
   - Why Max: orchestration touches multiple stages and error paths; regressions can silently skip work or break alerts/telemetry.

---

## Before you run an expensive model (checklist)

- **Scope the change**
  - Identify the minimal set of files likely involved (e.g., `scripts/run_daily.py`, `scripts/enrich_jobs.py`, `src/ji_engine/config.py`, `tests/…`)
  - State constraints explicitly: “docs-only”, “no behavior change”, “keep outputs stable”, etc.
- **Ask for a diff-first plan**
  - Request: “Propose exact files to touch and the minimal patch plan before editing.”
  - If you already know the files, name them.
- **Isolate for determinism**
  - Ensure tests use `tmp_path` and env overrides rather than writing to `./data`
  - Keep concurrency bounded (`max_workers=1`) when generating golden fixtures
- **Prefer surgical output**
  - Ask for: “diff-only changes”, “no reformatting”, “avoid unrelated cleanups”
- **Require verification**
  - Ask the model to run: `pytest -q` (or targeted tests) and to show failures/fixes
  - If a change touches orchestration: run at least one end-to-end smoke (`--no_post`, snapshot mode)

---

## Repo-specific notes that affect model choice

- **`scripts/run_daily.py` is the blast radius**
  - It orchestrates scraping → classification → enrichment → scoring → alerts/telemetry. Small mistakes cascade.
- **Enrichment is concurrency-sensitive**
  - `scripts/enrich_jobs.py` uses a thread pool and must preserve deterministic ordering for stable outputs and tests.
- **Provider interfaces are “integration seams”**
  - AI augmentation and embedding providers/caches are designed to be stubbed/offline in CI. Avoid models that “helpfully” add live calls unless explicitly requested.
- **Golden masters must be stable**
  - Tests that assert top-N ranked jobs rely on deterministic inputs, deterministic ordering, and bounded work.

