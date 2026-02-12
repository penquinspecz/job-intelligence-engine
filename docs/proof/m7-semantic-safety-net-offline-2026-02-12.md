# SignalCraft M7 Proof Receipt: Semantic Safety Net (Offline)

Date: 2026-02-12  
Scope: deterministic offline proof for bounded semantic safety net (JIE internals)

## Purpose

Prove that semantic scoring is active, bounded, and artifact-backed without live scraping or external services.

## Required Environment

```bash
export AWS_CONFIG_FILE=/dev/null
export AWS_SHARED_CREDENTIALS_FILE=/dev/null
export AWS_EC2_METADATA_DISABLED=true

export SEMANTIC_ENABLED=1
export SEMANTIC_MODEL_ID=deterministic-hash-v1
export SEMANTIC_TOP_K=3
export SEMANTIC_MAX_JOBS=10
export SEMANTIC_MIN_SIMILARITY=0.0
export SEMANTIC_MAX_BOOST=5
export JOBINTEL_RUN_ID=m7-proof-2026-02-12
```

## Exact Commands

```bash
make format
make lint
AWS_CONFIG_FILE=/dev/null AWS_SHARED_CREDENTIALS_FILE=/dev/null AWS_EC2_METADATA_DISABLED=true ./.venv/bin/python -m pytest -q tests/test_m7_semantic_proof_receipt.py
AWS_CONFIG_FILE=/dev/null AWS_SHARED_CREDENTIALS_FILE=/dev/null AWS_EC2_METADATA_DISABLED=true ./.venv/bin/python -m pytest -q
```

## Expected Artifacts

For run id `m7-proof-2026-02-12`:

- `state/runs/m7proof20260212/run_report.json`
- `state/runs/m7proof20260212/semantic/semantic_summary.json`
- `state/runs/m7proof20260212/semantic/semantic_scores.json`
- `state/runs/m7proof20260212/semantic/scores_openai_cs.json`
- `state/embeddings/deterministic-hash-v1/*.json`

## How To Inspect Semantic Evidence

```bash
cat state/runs/m7proof20260212/semantic/semantic_summary.json
cat state/runs/m7proof20260212/semantic/semantic_scores.json
```

Check:
- `semantic_summary.json` has `enabled=true`, `model_id=deterministic-hash-v1`, cache counters, and `embedded_job_count`.
- `semantic_scores.json` entries include `job_id`, `base_score`, `similarity`, `semantic_boost`, `final_score`, and `reasons`.
- At least one entry has `semantic_boost > 0`.
- Contract holds: `final_score == clamp(round(base_score + semantic_boost), 0, 100)`.

## Failure Modes Checklist

- `semantic_summary.json` missing:
  `run_daily` did not finalize semantic artifacts for the run id.
- `semantic_scores.json` empty:
  no ranked jobs reached semantic evaluation (`SEMANTIC_TOP_K`, input availability, or score stage failure).
- all boosts `0`:
  `SEMANTIC_MIN_SIMILARITY` too high or similarities non-positive for selected jobs.
- `unsupported_model_id:*` in skipped reason:
  `SEMANTIC_MODEL_ID` was not `deterministic-hash-v1`.
- run id mismatch:
  `JOBINTEL_RUN_ID` was unset or overridden incorrectly.
