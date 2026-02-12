# Semantic Safety Net (Current Runtime Contract)

SignalCraft product name is used in documentation. Some environment variables and paths still use legacy `JOBINTEL_*` naming in code/runtime.

## Scope

This document describes the semantic system that currently ships in the repo.
It covers deterministic behavior, mode semantics, and artifact contracts.

## Deterministic Foundations

Semantic behavior is deterministic by design:

- Embedding backend default: `deterministic-hash-v1`
- Backend/version marker: `deterministic-hash-backend-v1`
- Normalization version marker: `semantic_norm_v1`
- Text normalization: lowercase + alphanumeric token extraction + space join (`normalize_text_for_embedding`)
- Similarity rounding: cosine similarity rounded to 6 decimals
- Cache keys include semantic threshold token (rounded to 6 decimals)

Code references:
- `src/ji_engine/semantic/core.py`
- `src/ji_engine/semantic/cache.py`
- `src/ji_engine/semantic/boost.py`
- `src/ji_engine/semantic/step.py`

## Runtime Modes

Environment controls:

- `SEMANTIC_ENABLED=1|0`
- `SEMANTIC_MODE=sidecar|boost` (defaults to `boost`)
- `SEMANTIC_MODEL_ID` (default `deterministic-hash-v1`)
- `SEMANTIC_MAX_JOBS` (default `200`)
- `SEMANTIC_TOP_K` (default `50`)
- `SEMANTIC_MAX_BOOST` (default `5`)
- `SEMANTIC_MIN_SIMILARITY` (default `0.72`)

### `SEMANTIC_MODE=sidecar`

- Semantic artifacts are still produced.
- `score_jobs.py` does not apply semantic boost in sidecar mode, so ranked scores are not semantically mutated.
- In `run_daily.py`, when semantic is enabled and upstream data would otherwise short-circuit, runtime currently bypasses the full short-circuit and re-runs deterministic scoring to ensure semantic evidence artifacts are produced.

### `SEMANTIC_MODE=boost`

- `score_jobs.py` applies bounded semantic boost deterministically.
- Boost is bounded by `SEMANTIC_MAX_BOOST` and gated by `SEMANTIC_MIN_SIMILARITY`.
- Final score remains clamped to `0..100`.

## Artifact Contract

Run-level semantic artifacts live under:

- `state/runs/<sanitized_run_id>/semantic/semantic_summary.json`
- `state/runs/<sanitized_run_id>/semantic/semantic_scores.json`
- `state/runs/<sanitized_run_id>/semantic/scores_<provider>_<profile>.json` (per-provider/profile evidence produced by scoring)

### `semantic_summary.json` (current fields)

Current aggregate summary includes:

- `enabled`
- `model_id`
- `embedding_backend_version`
- `policy`
  - `max_jobs`
  - `top_k`
  - `max_boost`
  - `min_similarity`
- `normalized_text_hash`
- `embedding_cache_key`
- `cache_hit_counts`
  - `hit`, `miss`, `write`, `profile_hit`, `profile_miss`
- `embedded_job_count`
- `skipped_reason`

Note on field expectations:
- `semantic_mode` is recorded in `run_report.json`, not in `semantic_summary.json`.
- `policy.mode`, `used_short_circuit`, and `attempted_provider_profiles` are not currently emitted in `semantic_summary.json` on main.

### `semantic_scores.json`

- Deterministically sorted aggregate list of semantic evidence entries from all `scores_<provider>_<profile>.json` files.
- In boost mode, entries include fields like `job_id`, `base_score`, `similarity`, `semantic_boost`, `final_score`, and `reasons`.

### `run_report.json` semantic contract fields

`run_report.json` includes:

- `semantic_enabled`
- `semantic_mode`
- `semantic_model_id`
- `semantic_threshold`
- `semantic_max_boost`
- `embedding_backend_version`

Reference: `scripts/run_daily.py` semantic contract persistence.

## Guardrails and Expected Outcomes

- Boost never exceeds configured `SEMANTIC_MAX_BOOST`.
- Boost is zero below `SEMANTIC_MIN_SIMILARITY`.
- All-zero boosts are a valid outcome for a run (not an error).
- If semantic is disabled, summary still exists with `enabled=false` and `skipped_reason="semantic_disabled"`.

## Offline-Safe Local Commands

### 1) Sidecar mode (no semantic score mutation)

```bash
JOBINTEL_RUN_ID="semantic-sidecar-local" \
SEMANTIC_ENABLED=1 \
SEMANTIC_MODE=sidecar \
SEMANTIC_MODEL_ID="deterministic-hash-v1" \
SEMANTIC_MAX_JOBS=200 \
SEMANTIC_TOP_K=50 \
./.venv/bin/python scripts/run_daily.py --offline --snapshot-only --providers openai --profiles cs
```

### 2) Boost mode (bounded semantic influence)

```bash
JOBINTEL_RUN_ID="semantic-boost-local" \
SEMANTIC_ENABLED=1 \
SEMANTIC_MODE=boost \
SEMANTIC_MODEL_ID="deterministic-hash-v1" \
SEMANTIC_MAX_JOBS=200 \
SEMANTIC_TOP_K=50 \
SEMANTIC_MAX_BOOST=5 \
SEMANTIC_MIN_SIMILARITY=0.72 \
./.venv/bin/python scripts/run_daily.py --offline --snapshot-only --providers openai --profiles cs
```

### 3) Direct scoring invocation (semantic evidence file path explicit)

```bash
SEMANTIC_ENABLED=1 SEMANTIC_MODE=boost \
./.venv/bin/python scripts/score_jobs.py \
  --profile cs \
  --provider_id openai \
  --in_path data/ashby_cache/openai_enriched_jobs.json \
  --out_json data/ashby_cache/openai_ranked_jobs.cs.json \
  --out_csv data/ashby_cache/openai_ranked_jobs.cs.csv \
  --out_families data/ashby_cache/openai_ranked_families.cs.json \
  --out_md data/ashby_cache/openai_shortlist.cs.md \
  --out_md_top_n data/ashby_cache/openai_top.cs.md \
  --semantic_scores_out state/runs/manual/semantic/scores_openai_cs.json
```
