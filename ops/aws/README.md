# AWS Deployment (Milestone 2)

## Minimal IAM policy (least privilege)
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "JobIntelS3Publish",
      "Effect": "Allow",
      "Action": [
        "s3:PutObject",
        "s3:PutObjectAcl",
        "s3:ListBucket"
      ],
      "Resource": [
        "arn:aws:s3:::YOUR_BUCKET_NAME",
        "arn:aws:s3:::YOUR_BUCKET_NAME/*"
      ]
    },
    {
      "Sid": "CloudWatchLogs",
      "Effect": "Allow",
      "Action": [
        "logs:CreateLogGroup",
        "logs:CreateLogStream",
        "logs:PutLogEvents"
      ],
      "Resource": "*"
    }
  ]
}
```

## Required environment (no secrets printed here)
Minimum for publish:
- `JOBINTEL_S3_BUCKET`
- `AWS_REGION` (or `AWS_DEFAULT_REGION`)
- `JOBINTEL_S3_PREFIX` (optional; default `jobintel`)

If you prefer a JobIntel-prefixed region, set `JOBINTEL_AWS_REGION` and map it to
`AWS_REGION` in the task env.

Optional integrations:
- `DISCORD_WEBHOOK_URL` (alerts + summaries)
- `JOBINTEL_DASHBOARD_URL` (links in summaries)
- `AI_ENABLED=1` (enable AI insights)
- `OPENAI_API_KEY` (required if AI is enabled)

Publish controls:
- `PUBLISH_S3=1` (enable publish on run completion)
- `PUBLISH_S3_DRY_RUN=1` (log-only publish)

## Artifact key layout (deterministic)
- `s3://<bucket>/<prefix>/runs/<run_id>/<relative_path>` (only artifacts in `run_report.json:verifiable_artifacts`)
- `s3://<bucket>/<prefix>/latest/<provider>/<profile>/<artifact_name>` (allowlist: ranked JSON/CSV, ranked families, shortlist, top)
- `s3://<bucket>/<prefix>/state/last_success.json`
- `s3://<bucket>/<prefix>/state/<provider>/<profile>/last_success.json`

## ECS task definition (outline)
- Image: `jobintel:latest`
- Command:
  - Deterministic: `python scripts/run_daily.py --profiles cs --providers openai --snapshot-only --no_post`
  - With publish: add `--publish-s3` (or set `PUBLISH_S3=1`)
- Environment: see “Required environment” above
- Volumes:
  - `/app/data` (snapshots + inputs) and `/app/state` (run history)
  - S3-only mode is **not** sufficient for inputs; snapshot files must be available via image or volume.
- Logging: CloudWatch Logs (awslogs driver)

## EventBridge schedule
- Rule: cron or rate (e.g., `rate(7 days)` for weekly)
- Target: ECS task (same task definition)

## Publish a run (dry-run, no AWS needed)
```bash
python scripts/publish_s3.py --run-id <run_id> --prefix jobintel --dry-run
```

## Publish a run (real upload)
```bash
python scripts/publish_s3.py --run-id <run_id> --bucket <bucket> --prefix jobintel
```

## Retention strategy
- Keep full run artifacts under `runs/<run_id>/` for as long as required by compliance.
- `latest/` keys and `state/last_success.json` are overwritten each successful run.

## Verify publish
```bash
aws s3 ls "s3://$JOBINTEL_S3_BUCKET/$JOBINTEL_S3_PREFIX/runs/<run_id>/"
aws s3 ls "s3://$JOBINTEL_S3_BUCKET/$JOBINTEL_S3_PREFIX/latest/openai/cs/"
aws s3 cp "s3://$JOBINTEL_S3_BUCKET/$JOBINTEL_S3_PREFIX/state/last_success.json" -
aws s3 cp "s3://$JOBINTEL_S3_BUCKET/$JOBINTEL_S3_PREFIX/state/last_success.json" - | jq -r '.run_id'
```

## CloudWatch logging basics
- Ensure `awslogs-group` and `awslogs-stream-prefix` are set in the task.
- Verify logs in CloudWatch: `/ecs/jobintel` (or your group).

## First run checklist
1. Verify snapshots are present in the container (`/app/data/*_snapshots/`).
2. Confirm `JOBINTEL_S3_BUCKET` and `AWS_REGION` are set (if publishing).
3. Run once with `--snapshot-only --no_post` (and `--publish-dry-run` if testing publish).
4. Check `state/runs/<run_id>/run_report.json` and S3 keys (if enabled).

## Common failures
- `AWS preflight failed: bucket is required` → missing `JOBINTEL_S3_BUCKET`.
- `AWS preflight failed: region is required` → missing `AWS_REGION`/`AWS_DEFAULT_REGION`.
- `credentials not detected` → task role not attached or env creds missing.
- `snapshot-only violation` → live provider selected; use snapshots or disable the provider.

## Quick runbook
1. Validate env vars:
   - `make aws-env-check`
2. Run once:
   - `PUBLISH_S3=1 make daily` (or `--publish-s3` on the command)
3. Publish an existing run:
   - `make publish-last RUN_ID=<run_id>`
