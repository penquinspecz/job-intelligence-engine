# Milestone 4 DR Rehearsal Receipt Bundle

Run id: `20260207T022326Z-dr`
JobIntel run_id: `2026-02-07T02:34:58.241858+00:00`

## What was proven
- Provisioned cold-standby cloud DR infra (EC2 + k3s) from Terraform.
- Restored DB/artifacts from real encrypted S3 backup.
- Ran exactly one in-cluster JobIntel job and captured logs.
- Torn down DR infra and verified no lingering EC2/SG spend resources.

## Core receipts
- Provisioning: `provision_terraform_apply_x86_ami.log`
- Restore: `restore.log`, `restore_verify.log`, `restore_receipt.json`
- Job run: `run.log`, `job_status.json`, `kubectl_wait_job.log`
- Teardown: `teardown.log`, `teardown_verify_no_lingering.log`
- Summary receipt: `dr_rehearsal_receipt.json`

## Rerun commands (cheapest path)
1. `python scripts/ops/backup_onprem.py --run-id <run_id> --backup-uri s3://<bucket>/<prefix>/backups/<run_id> --bundle-root ops/proof/bundles --region us-east-1`
2. `terraform -chdir=ops/dr/terraform apply -auto-approve -var region=us-east-1 -var vpc_id=<vpc> -var subnet_id=<subnet> -var instance_type=t3.small -var ami_id=<ubuntu-amd64-ami> -var key_name=<ec2-key>`
3. Restore backup to DR host (see `restore.log` flow).
4. Run one job: apply `jobintel-dr-once.yaml` and `kubectl -n jobintel wait --for=condition=complete job/jobintel-dr-once`
5. Teardown: `terraform -chdir=ops/dr/terraform destroy -auto-approve -var ...` then verify no lingering EC2/SG.
