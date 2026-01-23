# AWS Deployment (Smoke)

## Required env vars / secrets
- `JOBINTEL_S3_BUCKET` (required)
- `JOBINTEL_S3_PREFIX` (optional, default `jobintel`)
- `DISCORD_WEBHOOK_URL` (optional)
- `JOBINTEL_DASHBOARD_URL` (optional)
- `OPENAI_API_KEY` (optional; AI features)
- `AI_ENABLED` / `AI_JOB_BRIEFS_ENABLED` (optional)
- `S3_PUBLISH_ENABLED=1` (required for publish)
- `S3_PUBLISH_REQUIRE=1` (fail-closed; recommended for prod)

## First Production Run (One-Off)
REQUIRED:
- `S3_PUBLISH_ENABLED=1`
- `S3_PUBLISH_REQUIRE=1`
- `JOBINTEL_S3_BUCKET`
- `JOBINTEL_S3_PREFIX`
- `OPENAI_API_KEY` (or equivalent provider keys)

OPTIONAL (recommended):
- `DISCORD_WEBHOOK_URL`
- `JOBINTEL_DASHBOARD_URL`

Secrets injection:
- Use AWS SSM Parameter Store or Secrets Manager.
- Do not store plaintext secrets in Terraform or task definitions.
- Pass secret ARNs via the Terraform `container_secrets` variable.

### Example secrets setup
SSM Parameter Store:
```bash
aws ssm put-parameter \
  --name "/jobintel/prod/OPENAI_API_KEY" \
  --type SecureString \
  --value "sk-...redacted..."

aws ssm put-parameter \
  --name "/jobintel/prod/DISCORD_WEBHOOK_URL" \
  --type SecureString \
  --value "https://discord.com/api/webhooks/..."
```

Secrets Manager:
```bash
aws secretsmanager create-secret \
  --name "jobintel/prod/OPENAI_API_KEY" \
  --secret-string "sk-...redacted..."

aws secretsmanager create-secret \
  --name "jobintel/prod/DISCORD_WEBHOOK_URL" \
  --secret-string "https://discord.com/api/webhooks/..."
```

Terraform example (`terraform.tfvars`):
```hcl
container_secrets = [
  {
    name      = "OPENAI_API_KEY"
    valueFrom = "arn:aws:ssm:us-east-1:123456789012:parameter/jobintel/prod/OPENAI_API_KEY"
  },
  {
    name      = "DISCORD_WEBHOOK_URL"
    valueFrom = "arn:aws:ssm:us-east-1:123456789012:parameter/jobintel/prod/DISCORD_WEBHOOK_URL"
  }
]
openai_api_key_ssm_param       = "arn:aws:ssm:us-east-1:123456789012:parameter/jobintel/prod/OPENAI_API_KEY"
discord_webhook_url_ssm_param  = "arn:aws:ssm:us-east-1:123456789012:parameter/jobintel/prod/DISCORD_WEBHOOK_URL"
```

## First production run checklist
1. Set required env vars:
   - `JOBINTEL_S3_BUCKET`
   - `JOBINTEL_S3_PREFIX` (if not using default)
   - `S3_PUBLISH_ENABLED=1`
   - `S3_PUBLISH_REQUIRE=1`
   - `DISCORD_WEBHOOK_URL` (optional but recommended)
   - `JOBINTEL_DASHBOARD_URL` (optional)
2. Store secrets securely:
   - Prefer AWS SSM Parameter Store or Secrets Manager.
   - Pass secret ARNs via the Terraform `container_secrets` variable.
3. Verify IAM task role has S3 + CloudWatch logs permissions.
4. Run `make aws-smoke` and confirm bucket/prefix access.
5. Trigger a one-off task run and verify:
   - `runs/<run_id>/` uploaded
   - `latest/<provider>/<profile>/` updated
   - CloudWatch logs include a RUN SUMMARY block

## Deploy (Terraform)
```bash
cd ops/aws/infra
terraform init
terraform apply
```

## One-off task
Run the ECS task definition directly in the console or:
```bash
aws ecs run-task \
  --cluster <cluster-arn> \
  --task-definition jobintel-daily \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[subnet-xxx],securityGroups=[sg-xxx],assignPublicIp=ENABLED}"
```
You can also print the command via:
```bash
make aws-first-run
```
Or use the tfvars-aware helper:
```bash
make aws-oneoff-run
```

## EventBridge invoke role
EventBridge uses a dedicated "events invoke role" to call `ecs:RunTask` and `iam:PassRole`.
The container runtime still uses `task_role` and `execution_role` for S3/SSM/logs access.
The task role also needs `s3:GetObject` for baseline resolution from `jobintel/state/last_success.json`
and `jobintel/runs/...` history.

## Baselines and deltas
- First run: baseline is `none`, so new=N is expected.
- Subsequent runs: baseline resolves from `s3://<bucket>/<prefix>/state/last_success.json` when available,
  otherwise S3 runs history is used. This avoids `new=N` on identical replays.
To inspect or reset baselines:
```bash
aws s3 cp s3://<bucket>/<prefix>/state/last_success.json -
aws s3 cp s3://<bucket>/<prefix>/state/<provider>/<profile>/last_success.json -
aws s3 rm s3://<bucket>/<prefix>/state/last_success.json
aws s3 rm s3://<bucket>/<prefix>/state/<provider>/<profile>/last_success.json
```

Verification:
- Check task role policy includes `s3:GetObject`:
  ```bash
  aws iam get-role-policy --role-name jobintel-task-role --policy-name jobintel-task-policy
  ```
- Run ECS task twice; the second run should not log `Changelog (cs): new=456` on unchanged inputs.
  To quickly inspect pointers and the latest run report:
  ```bash
  BUCKET=<bucket> PREFIX=<prefix> PROVIDER=openai PROFILE=cs ./scripts/verify_s3_pointers.sh
  ```

## OpenAI scraping source
- OpenAI jobs are sourced from the Ashby board: `https://jobs.ashbyhq.com/openai`.
- The legacy `openai.com/careers` scraper is deprecated due to WAF/403 risk.

## Verify S3 uploads
Expected keys:
- `s3://<bucket>/<prefix>/runs/<run_id>/...`
- `s3://<bucket>/<prefix>/latest/<provider>/<profile>/...`

Check:
```bash
aws s3 ls s3://<bucket>/<prefix>/runs/ --recursive | head
aws s3 ls s3://<bucket>/<prefix>/latest/ --recursive | head
```

## Smoke script
```bash
python scripts/aws_deploy_smoke.py --bucket <bucket> --prefix <prefix>
```

## Schedule status (proof of runs)
```bash
make aws-schedule-status
```

## CloudWatch alarm recommendations
- Task failure alarm: alert when ECS tasks in the scheduled rule stop with non-zero exit or `STOPPED` reason.
- Log-based alarm: create a metric filter on `RUN SUMMARY` and alert if missing for > 1 run interval.
- Optional: alert on provider unavailable rate > threshold (e.g., match `provider_availability` with `unavailable`).
