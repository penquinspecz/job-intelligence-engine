# SignalCraft Ops Runbook (ECS + S3)

Note: SignalCraft is the product name. Some env vars/paths in commands still use legacy `JOBINTEL_*` naming because that is current runtime truth.

## Happy path
```bash
./scripts/deploy_ecs_rev.sh
TASKDEF_REV=<newrev> bash ./scripts/run_ecs_once.sh
BUCKET=jobintel-prod1 PREFIX=jobintel bash ./scripts/verify_ops.sh
BUCKET=jobintel-prod1 PREFIX=jobintel bash ./scripts/show_run_provenance.sh
aws s3 ls s3://jobintel-prod1/jobintel/latest/openai/cs/
./scripts/print_taskdef_env.sh TASKDEF_REV=<newrev>
```

## Verify provenance
```bash
# Show build provenance from last_success (or provider/profile) pointer
BUCKET=jobintel-prod1 PREFIX=jobintel PROVIDER=openai PROFILE=cs bash ./scripts/show_run_provenance.sh
```
Note: ECS task ARN is resolved via ECS task metadata when available.

## Publish to S3
```bash
PUBLISH_S3=1 JOBINTEL_S3_BUCKET=jobintel-prod1 JOBINTEL_S3_PREFIX=jobintel \
  python scripts/run_daily.py --profiles cs --providers openai --no_post

aws s3 ls s3://jobintel-prod1/jobintel/runs/<run_id>/<provider>/<profile>/
aws s3 ls s3://jobintel-prod1/jobintel/latest/openai/cs/
```

## Failure modes
```bash
# Pointers missing or access denied
BUCKET=jobintel-prod1 PREFIX=jobintel bash ./scripts/verify_ops.sh

# Show build provenance from last_success pointer
BUCKET=jobintel-prod1 PREFIX=jobintel bash ./scripts/show_run_provenance.sh

# Inspect task env + image
TASKDEF_REV=<newrev> ./scripts/print_taskdef_env.sh

# Inspect task runtime status
CLUSTER_ARN=<cluster> TASK_ARN=<task> REGION=us-east-1 ./scripts/ecs_verify_task.sh

# Publish disabled or missing bucket
PUBLISH_S3=1 python scripts/run_daily.py --profiles cs --providers openai --no_post
```
