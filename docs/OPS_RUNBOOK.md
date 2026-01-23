# Ops: One-off run debugging (ECS + S3 + Logs)

## Quick start
```bash
pip install -e .[dev]
BUCKET=<bucket> PREFIX=jobintel ./scripts/aws_debug_latest.py
BUCKET=<bucket> PREFIX=jobintel PROVIDER=openai PROFILE=cs ./scripts/aws_debug_latest.py
BUCKET=<bucket> PREFIX=jobintel PROVIDER=openai PROFILE=cs ./scripts/verify_s3_pointers.sh
BUCKET=<bucket> PREFIX=jobintel PROVIDER=openai PROFILE=cs ./scripts/verify_ops.sh
```

## One-command verification
```bash
BUCKET=<bucket> PREFIX=jobintel PROVIDER=openai PROFILE=cs ./scripts/verify_ops.sh
```

## macOS-friendly alternatives to `watch`
```bash
while true; do date; aws logs filter-log-events --log-group-name /ecs/jobintel --start-time $((($(date +%s)-300)*1000)) --filter-pattern "RUN SUMMARY" | head -n 20; sleep 15; done
```

## CloudWatch Logs filter patterns (safe characters)
Avoid `/` in patterns; use simple terms:
```bash
aws logs filter-log-events --log-group-name /ecs/jobintel --start-time $((($(date +%s)-1800)*1000)) --filter-pattern "baseline"
aws logs filter-log-events --log-group-name /ecs/jobintel --start-time $((($(date +%s)-1800)*1000)) --filter-pattern "last_success"
aws logs filter-log-events --log-group-name /ecs/jobintel --start-time $((($(date +%s)-1800)*1000)) --filter-pattern "uploaded"
aws logs filter-log-events --log-group-name /ecs/jobintel --start-time $((($(date +%s)-1800)*1000)) --filter-pattern "error"
```

## S3 commands
List latest runs:
```bash
aws s3 ls s3://<bucket>/jobintel/runs/ | tail -n 5
```

Fetch latest run_report.json:
```bash
RUN_ID=$(aws s3 ls s3://<bucket>/jobintel/runs/ | awk '{print $2}' | sort | tail -n 1)
aws s3 cp s3://<bucket>/jobintel/runs/$RUN_ID/run_report.json -
```

Fetch last_success pointer:
```bash
aws s3 cp s3://<bucket>/jobintel/state/last_success.json -
aws s3 cp s3://<bucket>/jobintel/state/openai/cs/last_success.json -
```

## Log time windows (last 30/60/120 minutes)
```bash
aws logs filter-log-events --log-group-name /ecs/jobintel --start-time $((($(date +%s)-1800)*1000))
aws logs filter-log-events --log-group-name /ecs/jobintel --start-time $((($(date +%s)-3600)*1000))
aws logs filter-log-events --log-group-name /ecs/jobintel --start-time $((($(date +%s)-7200)*1000))
```

## CloudWatch tail helper (safe filters)
```bash
LOG_GROUP=/ecs/jobintel REGION=us-east-1 LOOKBACK_MINUTES=60 FILTER=baseline ./scripts/cw_tail.sh
LOG_GROUP=/ecs/jobintel REGION=us-east-1 LOOKBACK_MINUTES=60 FILTER=last_success ./scripts/cw_tail.sh
```

## ECS task inspection
```bash
CLUSTER_ARN=<cluster> TASK_ARN=<task> REGION=us-east-1 ./scripts/ecs_verify_task.sh
```

## One-off ECS run wrapper
```bash
CLUSTER_ARN=<cluster> TASK_FAMILY=jobintel-daily REGION=us-east-1 \
SUBNET_IDS=subnet-aaa,subnet-bbb SECURITY_GROUP_IDS=sg-123 \
BUCKET=<bucket> PREFIX=jobintel PROVIDER=openai PROFILE=cs \
./scripts/run_ecs_once.sh
```

Optional flags (env-only):
```bash
TAIL_LOGS=1 LOOKBACK_MINUTES=60 PRINT_RUN_REPORT=1 \
CLUSTER_ARN=<cluster> TASK_FAMILY=jobintel-daily REGION=us-east-1 \
SUBNET_IDS=subnet-aaa,subnet-bbb SECURITY_GROUP_IDS=sg-123 \
BUCKET=<bucket> PREFIX=jobintel PROVIDER=openai PROFILE=cs \
./scripts/run_ecs_once.sh
```

## Troubleshooting: diff_counts show all-new
1. Verify pointers + latest run success:
   `./scripts/verify_ops.sh`
2. If pointers missing, ensure S3 publish env vars are set and task role can `s3:GetObject`.
3. If baseline reads show `access_denied`, fix IAM and rerun.
4. If pointers are stale, reset them:
   `aws s3 rm s3://<bucket>/jobintel/state/last_success.json`
