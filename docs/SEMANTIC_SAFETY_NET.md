# Semantic Safety Net (Milestone 7)

## What this is
The semantic safety net is an offline, deterministic diff pipeline that detects
regressions between two job outputs (baseline vs candidate). It is designed to
surface extraction regressions and ranking drift without any network calls or
LLM usage.

## What we detect
- Schema drift: missing fields or shape changes in job records.
- Field omissions: completeness drops for critical fields (e.g., `apply_url`).
- Dedupe regressions: increased duplicates or changed job IDs for the same job.
- Job ID instability: the same job content resolving to a different `job_id`.
- Ranking feature drift: large field deltas in ranked job outputs.

## What we do not claim
- No human judgment or semantic correctness beyond deterministic checks.
- No ability to validate job descriptions against live sources.
- No network-based validation or LLM-based classification.

## Deterministic principles
- Inputs are local files (run artifacts or snapshot outputs).
- Outputs are stable JSON + a deterministic text summary.
- All ordering is sorted and stable; no timestamps are emitted.
- No network access and no dependency on system time or environment.

## How to use (examples)
1. Compare ranked outputs from two runs:
```bash
python -m src.jobintel.cli safety diff \
  --baseline state/runs/2026-02-01T00-00-00Z/run_report.json \
  --candidate state/runs/2026-02-02T00-00-00Z/run_report.json \
  --provider openai --profile cs
```
2. Compare two ranked job JSON files directly:
```bash
python -m src.jobintel.cli safety diff \
  --baseline data/openai_ranked_jobs.cs.json \
  --candidate data/openai_ranked_jobs.cs.json
```
3. Compare fixture outputs (offline testable paths):
```bash
python -m src.jobintel.cli safety diff \
  --baseline tests/fixtures/safety_diff/baseline.json \
  --candidate tests/fixtures/safety_diff/candidate.json
```

## Output contract
The report includes:
- `counts`: totals, new, removed, changed.
- `job_id_churn`: overlap count, churn rate, and examples.
- `field_completeness`: percent non-empty per field (baseline vs candidate).
- `changes_top`: top-N field diff records.
- `risk_score` + `risk_reasons`: deterministic scoring for suspicious change.

The summary prints a short, human-readable line for quick inspection.
