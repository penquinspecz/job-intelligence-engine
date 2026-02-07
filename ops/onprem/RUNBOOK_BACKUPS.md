# Runbook: Backups (On-Prem Primary)

This runbook defines the Milestone 4 backup contract without requiring live cloud calls.

## Required Inputs

- `AWS_REGION`
- `BACKUP_BUCKET`
- `BACKUP_PREFIX`
- `BACKUP_URI` in `s3://<bucket>/<prefix>/backups/<backup_id>` format

## Plan-Mode Proof Command

```bash
python scripts/ops/prove_it_m4.py \
  --plan \
  --run-id m4-backup-plan \
  --output-dir ops/proof/bundles \
  --aws-region us-east-1 \
  --backup-bucket <bucket> \
  --backup-prefix <prefix>/backups/m4-backup-plan \
  --backup-uri s3://<bucket>/<prefix>/backups/m4-backup-plan
```

Expected receipts:

- `ops/proof/bundles/m4-m4-backup-plan/backup_plan.json`
- `ops/proof/bundles/m4-m4-backup-plan/manifest.json`

## Restore Contract Check

```bash
scripts/ops/dr_restore.sh --backup-uri s3://<bucket>/<prefix>/backups/<backup_id>
```

The command verifies that required objects exist:

- `metadata.json`
- `state.tar.zst`
- `manifests.tar.zst`

## Execute Mode (Operator Controlled)

Use execute mode only during scheduled DR rehearsal windows:

```bash
python scripts/ops/prove_it_m4.py \
  --execute \
  --run-id m4-dr-rehearsal-<timestamp> \
  --aws-region <region> \
  --backup-bucket <bucket> \
  --backup-prefix <prefix>/backups/<backup_id> \
  --backup-uri s3://<bucket>/<prefix>/backups/<backup_id>
```
