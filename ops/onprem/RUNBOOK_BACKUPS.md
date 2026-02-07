# Runbook: Backups (On-Prem Primary)

This runbook defines backup + verify + restore checks for Milestone 4.

## Preflight checks

```bash
python --version
aws --version
test -n "$AWS_REGION" && echo AWS_REGION=ok
test -n "$BACKUP_BUCKET" && echo BACKUP_BUCKET=ok
test -n "$BACKUP_PREFIX" && echo BACKUP_PREFIX=ok
```

Success criteria:
- Required env vars are present.
- Operator has IAM permissions for backup bucket prefix.

If it fails:
- Fix credentials/role first; do not run partial backup.

## 1) Plan-mode contract (safe default)

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

## 2) Execute one backup run

```bash
python scripts/ops/backup_onprem.py \
  --run-id 20260207T000000Z \
  --bundle-root ops/proof/bundles \
  --aws-region "$AWS_REGION" \
  --backup-bucket "$BACKUP_BUCKET" \
  --backup-prefix "$BACKUP_PREFIX"
```

Success criteria:
- backup receipt written.
- checksum verification log written.

If it fails:
- inspect `ops/proof/bundles/m4-<run_id>/backup.log`
- inspect `ops/proof/bundles/m4-<run_id>/checksum_verify.log`

## 3) Restore verification (contract check)

```bash
python scripts/ops/restore_onprem.py \
  --run-id 20260207T000000Z \
  --bundle-root ops/proof/bundles \
  --backup-uri s3://<bucket>/<prefix>/backups/20260207T000000Z
```

Success criteria:
- restore receipt exists with restored artifact counts.
- verify log shows expected files present.

If it fails:
- inspect `ops/proof/bundles/m4-<run_id>/restore.log`
- inspect `ops/proof/bundles/m4-<run_id>/restore_verify.log`

## 4) Retention policy contract

- Daily backups: keep 14 days.
- Weekly backups: keep 8 weeks.
- Backups are encrypted + checksummed before acceptance.
