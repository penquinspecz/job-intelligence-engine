# Architecture

## Pipeline stages

Primary entrypoint: `scripts/run_daily.py`.

Stages (in order):
- Scrape: `scripts/run_scrape.py` (snapshot or live).
- Classify: `scripts/run_classify.py` (labels jobs).
- Enrich: `scripts/enrich_jobs.py` (optional, controlled by `--no_enrich`).
- AI augment: `scripts/run_ai_augment.py` (optional, controlled by `--ai` / `--ai_only`).
- Score: `scripts/score_jobs.py` (produces ranked JSON/CSV/MD and families JSON).
- Diff + archive: compares ranked outputs and writes history/run metadata.

## Determinism rules

- Stable inputs yield stable outputs (no random run UUIDs in artifacts).
- Scoring inputs are selected deterministically based on flags and file freshness.
- Job identity uses a normalized URL or title/location fallback.
- Content changes are tracked via `content_fingerprint` in ranked output.
- Sorting uses score desc, then job identity as a stable tiebreaker.
- Run reports are written to `state/runs/<run_id>.json` with stable ordering.

## Kubernetes CronJob deployment

- See `ops/k8s/` for a minimal CronJob + PVC setup.
- Default command: `python scripts/run_daily.py --profiles cs --us_only --no_post --no_enrich`.
- Mount `/app/data` and `/app/state` via PVCs for persistence.
- Security defaults: non-root, read-only root filesystem, dropped capabilities, `RuntimeDefault` seccomp.

## Replay tooling

- Use `scripts/replay_run.py` with a run report to verify input/output hashes.
- The run report documents selected inputs, outputs, and selection reasons.
- For scoring-only replay, re-run `scripts/score_jobs.py` with the recorded `--in_path` and compare output hashes.
