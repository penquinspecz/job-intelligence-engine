# AWS Deployment (Milestone 2)

## EKS + ECR golden path

Use `ops/aws/EKS_ECR_GOLDEN_PATH.md` for the copy/paste flow:
- bootstrap EKS with Terraform
- build and push image to ECR
- render/apply `aws-eks` overlay with explicit image
- run `scripts/aws_preflight_eks.py` to validate identity/cluster/ECR/S3 before proof runs

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
        "s3:GetObject",
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

Notes:
- `PutObjectAcl` is not required (no ACLs are set in code).
- `GetObject` + `ListBucket` are required for baseline resolution and run history lookups.
- `HeadObject` is only needed for live verification (`verify_published_s3.py` without `--offline`). Treat that as an
  operator/debug role rather than the runtime role.

## IRSA and role separation (EKS)

Runtime role (CronJob / Job pods):
- Attach the least-privilege S3 policy above to the IAM role referenced by the ServiceAccount annotation.
- This role is used by the running JobIntel pod to publish artifacts and resolve baselines.

Operator verify role (human/automation):
- For `verify_published_s3.py` without `--offline`, grant `s3:HeadObject` (and optionally `s3:GetObject`) to the
  role used by the operator or verification job.

Cluster admin steps (out-of-band):
- Create the IAM role and map it to the ServiceAccount via IRSA.
- Apply the K8s manifests/overlays that reference the ServiceAccount annotation.

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
- `s3://<bucket>/<prefix>/runs/<run_id>/<provider>/<profile>/<artifact_name>` (verifiable outputs; allowlist)
- `s3://<bucket>/<prefix>/runs/<run_id>/<relative_path>` (non-provider artifacts like input archives)
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

## Verify published artifacts (recommended)
```bash
make verify-publish RUN_ID=<run_id>
make verify-publish RUN_ID=<run_id> VERIFY_LATEST=1
make verify-publish-live RUN_ID=<run_id> VERIFY_LATEST=1
```

Offline vs live semantics:
- `make verify-publish` is offline by default: it computes the expected key list from the run report and does **not** call AWS.
- `make verify-publish-live` performs real S3 `HeadObject` checks and requires valid AWS credentials.

Exit codes:
- `0` success (all expected objects present)
- `2` validation/missing run report or missing objects
- `>=3` runtime errors


## Publish a run (real upload)
```bash
python scripts/publish_s3.py --run-id <run_id> --bucket <bucket> --prefix jobintel
```

Ordering:
- Publish uploads `runs/<run_id>/...` keys first, then updates `latest/<provider>/<profile>/...` keys.

## Retention strategy
- Keep full run artifacts under `runs/<run_id>/` for as long as required by compliance (recommended: lifecycle rule).
- `latest/` keys and `state/last_success.json` are overwritten each successful run and should be retained indefinitely.

## Verify publish
```bash
aws s3 ls "s3://$JOBINTEL_S3_BUCKET/$JOBINTEL_S3_PREFIX/runs/<run_id>/<provider>/<profile>/"
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
