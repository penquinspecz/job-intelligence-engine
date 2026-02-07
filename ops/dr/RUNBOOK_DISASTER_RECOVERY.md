# Runbook: Disaster Recovery (Cold Standby)

This runbook executes deterministic bringup -> restore -> validate -> teardown.

## Preflight checks

```bash
aws sts get-caller-identity
terraform -chdir=ops/dr/terraform version
scripts/ops/dr_contract.py --backup-uri s3://<bucket>/<prefix>/backups/<backup_id>
```

Success criteria:
- AWS identity resolves to operator account.
- Terraform available.
- Backup URI passes contract check.

If it fails:
- stop before `APPLY=1`; fix IAM/backup inputs first.

## 1) One-command plan bundle (safe default)

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

## 2) Execute DR rehearsal

```bash
APPLY=1 scripts/ops/dr_bringup.sh
scripts/ops/dr_restore.sh --backup-uri s3://<bucket>/<prefix>/backups/<backup_id>
RUN_JOB=1 scripts/ops/dr_validate.sh
CONFIRM_DESTROY=1 scripts/ops/dr_teardown.sh
```

Success criteria:
- Infra comes up, one JobIntel run executes, teardown removes cloud infra.

If it fails:
- bringup: inspect `ops/proof/bundles/m4-<run_id>/provision_terraform_apply*.log`
- restore: inspect `ops/proof/bundles/m4-<run_id>/restore.log`
- validate: inspect `ops/proof/bundles/m4-<run_id>/run.log`
- teardown: inspect `ops/proof/bundles/m4-<run_id>/teardown.log`

## 3) Post-run spend safety check

```bash
aws ec2 describe-instances --filters Name=tag:Project,Values=jobintel-dr Name=instance-state-name,Values=running
aws eks list-clusters
```

Success criteria:
- No lingering DR compute resources unless explicitly retained for debugging.
