# SignalCraft Milestone 5 Proof Receipt (Offline Multi-Provider)

SignalCraft (product) proof for the internal Job Intelligence Engine (JIE) multi-provider determinism contract.

## Receipt Summary
- run_id: `m5-proof-2026-02-11T23:59:15Z`
- providers attempted: `openai`, `scaleai`, `replit`
- execution mode: offline + snapshot-only (no live network scraping)

## Exact Commands Run
```bash
export JOBINTEL_RUN_ID='m5-proof-2026-02-11T23:59:15Z'
export AWS_CONFIG_FILE=/dev/null
export AWS_SHARED_CREDENTIALS_FILE=/dev/null
export AWS_EC2_METADATA_DISABLED=true

./.venv/bin/python scripts/run_daily.py \
  --providers openai,scaleai,replit \
  --providers-config config/providers.json \
  --profiles cs \
  --offline \
  --snapshot-only \
  --no_post \
  --no_enrich
```

## Artifact Paths In Repo
- run artifacts dir: `state/runs/m5proof20260211T235915Z/`
- run report: `state/runs/m5proof20260211T235915Z/run_report.json`
- ranked outputs:
  - `data/ashby_cache/openai_ranked_jobs.cs.json`
  - `data/ashby_cache/scaleai_ranked_jobs.cs.json`
  - `data/ashby_cache/replit_ranked_jobs.cs.json`

## Provider Provenance (from run_report.json)
- openai: extraction_mode=`ashby`, availability=`available`, scrape_mode=`snapshot`, parsed_job_count=`493`, snapshot_path=`data/openai_snapshots/index.html`
- scaleai: extraction_mode=`ashby`, availability=`available`, scrape_mode=`snapshot`, parsed_job_count=`2`, snapshot_path=`data/scaleai_snapshots/index.html`
- replit: extraction_mode=`ashby`, availability=`available`, scrape_mode=`snapshot`, parsed_job_count=`2`, snapshot_path=`data/replit_snapshots/index.html`

## If This Fails, Inspect
- CLI log line for run id: `JOBINTEL_RUN_ID=...`
- run report provider contract: `state/runs/m5proof20260211T235915Z/run_report.json`
  - `providers` must be stable and deterministic
  - `provenance_by_provider.<provider>.extraction_mode` must be present for every attempted provider
- provider snapshots:
  - `data/openai_snapshots/index.html`
  - `data/scaleai_snapshots/index.html`
  - `data/replit_snapshots/index.html`
