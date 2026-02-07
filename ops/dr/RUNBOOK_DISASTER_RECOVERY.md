# Runbook: Disaster Recovery (Cold Standby)

This runbook executes a deterministic bringup/restore/validate/teardown contract.

## One-Command Plan Bundle

```bash
python scripts/ops/prove_it_m4.py \
  --plan \
  --run-id m4-dr-plan \
  --output-dir ops/proof/bundles \
  --aws-region us-east-1 \
  --backup-bucket <bucket> \
  --backup-prefix <prefix>/backups/m4-dr-plan \
  --backup-uri s3://<bucket>/<prefix>/backups/m4-dr-plan
```

Expected receipts:

- `ops/proof/bundles/m4-m4-dr-plan/onprem_plan.txt`
- `ops/proof/bundles/m4-m4-dr-plan/backup_plan.json`
- `ops/proof/bundles/m4-m4-dr-plan/dr_plan.txt`
- `ops/proof/bundles/m4-m4-dr-plan/manifest.json`

## Step-by-Step Execute Commands

```bash
APPLY=1 scripts/ops/dr_bringup.sh
scripts/ops/dr_restore.sh --backup-uri s3://<bucket>/<prefix>/backups/<backup_id>
RUN_JOB=1 scripts/ops/dr_validate.sh
CONFIRM_DESTROY=1 scripts/ops/dr_teardown.sh
```

## Verify Restore Inputs

```bash
scripts/ops/dr_contract.py --backup-uri s3://<bucket>/<prefix>/backups/<backup_id>
```

This command prints the required object keys and should be treated as the contract source of truth.
