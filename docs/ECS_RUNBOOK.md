# ECS Scheduled Run Runbook (SignalCraft)

This runbook documents how to run SignalCraft as a scheduled ECS task with deterministic outputs and verifiable publish artifacts. It does **not** perform any AWS actions; it only defines the steps and the proof you should capture.

Note: SignalCraft is the product name. Some env vars/paths in commands still use legacy `JOBINTEL_*` naming because that is current runtime truth.

## Prerequisites

- AWS account with VPC + private subnets (or public subnets with NAT/IGW if needed)
- Security group allowing outbound HTTPS to S3/Discord/OpenAI (if enabled)
- ECR image pushed (e.g., `ghcr.io/<org>/jobintel:<tag>` or ECR)
- S3 bucket for artifacts (e.g., `jobintel-artifacts`)
- (Optional) Discord webhook for alerts
- (Optional) OpenAI API key if AI insights are enabled

## ECS Task Definition (outline)

Key properties:
- **CPU/Memory:** start with `1024/2048` (adjust per run time)
- **Command:**
  - `python scripts/run_daily.py --profiles cs --us_only --no_post --snapshot-only --offline`
  - add `--publish-s3` if you want real S3 uploads
- **Environment variables:**
  - `JOBINTEL_S3_BUCKET`, `JOBINTEL_S3_PREFIX`, `AWS_REGION` (or `AWS_DEFAULT_REGION`)
  - `CAREERS_MODE=SNAPSHOT`, `EMBED_PROVIDER=stub`, `ENRICH_MAX_WORKERS=1`
  - `PUBLISH_S3=1` and `PUBLISH_S3_DRY_RUN=0` for real publish
  - `DISCORD_WEBHOOK_URL` (optional)
  - `OPENAI_API_KEY` (optional)
- **Mounts:**
  - `/app/data` (snapshots + inputs)
  - `/app/state` (run registry + artifacts)

See `ops/aws/ecs/taskdef.template.json` for placeholders.

## Schedule via EventBridge

Create a scheduled rule that triggers the ECS task on a cron schedule.
- Example schedule: `cron(0 13 * * ? *)`
- Target: ECS task definition + cluster

See `ops/aws/ecs/eventbridge-rule.template.json` for placeholders.

## Inspect the Last Run

1) **CloudWatch logs**: confirm the run completed and capture the `run_id`.
2) **Run report**: in `/app/state/runs/<run_id>/run_report.json` (inside task container or S3 if published).
3) **S3 keys** (if publish enabled):
   - `s3://<bucket>/<prefix>/runs/<run_id>/<provider>/<profile>/...`
   - `s3://<bucket>/<prefix>/latest/<provider>/<profile>/...`

## Rollback Steps

1) **Pin image tag**: redeploy the last known-good image tag.
2) **Disable schedule**: disable the EventBridge rule.
3) **Revert task definition**: set task definition back to the previous revision.

## Rotate Secrets

Preferred sources:
- AWS Secrets Manager or SSM Parameter Store

Steps:
1) Update the secret (e.g., `OPENAI_API_KEY`, `DISCORD_WEBHOOK_URL`).
2) Update task definition to reference new version.
3) Force a new task deployment or run a one-off task.
4) Validate with the commands below.

## One-time Proof Checklist (capture these)

- **CloudWatch log** line showing `run_id`.
- **Run report** exists in `state/runs/<run_id>/run_report.json`.
- **Publish plan JSON** (offline):
  ```bash
  python scripts/publish_s3.py --run-id <run_id> --plan --json > /tmp/publish_plan.json
  ```
- **Offline verification**:
  ```bash
  python scripts/verify_published_s3.py --offline --plan-json /tmp/publish_plan.json
  ```
- **S3 verification (if publishing)**:
  ```bash
  python scripts/verify_published_s3.py --bucket "$JOBINTEL_S3_BUCKET" --run-id <run_id> --verify-latest
  ```

Keep screenshots or log excerpts of the above for Milestone 2 proof.
