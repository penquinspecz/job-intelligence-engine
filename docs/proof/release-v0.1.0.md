# Release Proof: v0.1.0

## Release Identity
- Tag: `v0.1.0`
- SHA: `b2e308e660bd0497702efd59a1e26ed35af2d08e`
- Release published (UTC): `2026-02-12T15:45:38Z`
- Release URL: https://github.com/penquinspecz/SignalCraft/releases/tag/v0.1.0
- Tag->SHA verification: `git rev-list -n 1 v0.1.0` == `git rev-parse HEAD`

## Commands Run
```bash
git fetch origin --tags
git describe --tags --always
git rev-parse HEAD

make format && make lint
AWS_CONFIG_FILE=/dev/null AWS_SHARED_CREDENTIALS_FILE=/dev/null AWS_EC2_METADATA_DISABLED=true PYTHONPATH=src ./.venv/bin/python -m pytest -q

JOBINTEL_RUN_ID="release-v0.1.0-smoke" SEMANTIC_ENABLED=0 \
./.venv/bin/python scripts/run_daily.py --offline --snapshot-only --providers openai --profiles cs
```

## Results
- `make format`: passed
- `make lint`: passed
- `pytest -q` (AWS-isolated): `509 passed, 15 skipped`
- Offline run: completed with deterministic short-circuit on unchanged artifacts

## Proof Lines (from offline run)
- `JOBINTEL_RUN_ID=release-v0.1.0-smoke`
- `run_id=release-v0.1.0-smoke`
- `s3_status=skipped`
- `s3_reason=skipped_status_short_circuit`
- `No changes detected (raw/labeled/enriched) and ranked artifacts present. Short-circuiting downstream stages (scoring not required).`

## Artifact Evidence
Run directory (normalized):
- `state/runs/releasev010smoke/`

Key artifacts:
- `state/runs/releasev010smoke/run_report.json`
- `state/runs/releasev010smoke/openai/cs/openai_ranked_jobs.cs.json`
- `state/runs/releasev010smoke/openai/cs/openai_ranked_jobs.cs.csv`
- `state/runs/releasev010smoke/semantic/semantic_summary.json`
- `state/runs/releasev010smoke/costs.json`

Semantic summary checks:
- `enabled=false`
- `skipped_reason="semantic_disabled"`

Cost artifact note:
- `costs.json` is present for this run.
