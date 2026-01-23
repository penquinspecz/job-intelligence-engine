#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 0 ]]; then
  echo "This script uses env vars only; no positional args are accepted." >&2
  echo "Example: CLUSTER_ARN=... TASK_FAMILY=jobintel-daily REGION=us-east-1 SUBNET_IDS=subnet-1,subnet-2 SECURITY_GROUP_IDS=sg-1 BUCKET=... PREFIX=jobintel ./scripts/run_ecs_once.sh" >&2
  exit 2
fi

CLUSTER_ARN="${CLUSTER_ARN:-}"
TASK_FAMILY="${TASK_FAMILY:-}"
TASKDEF_ARN="${TASKDEF_ARN:-}"
TASKDEF_REV="${TASKDEF_REV:-}"
REQUIRE_LATEST_TASKDEF="${REQUIRE_LATEST_TASKDEF:-1}"
REGION="${REGION:-${AWS_REGION:-us-east-1}}"
SUBNET_IDS="${SUBNET_IDS:-}"
SECURITY_GROUP_IDS="${SECURITY_GROUP_IDS:-}"
BUCKET="${BUCKET:-${JOBINTEL_S3_BUCKET:-}}"
PREFIX="${PREFIX:-${JOBINTEL_S3_PREFIX:-jobintel}}"
PROVIDER="${PROVIDER:-openai}"
PROFILE="${PROFILE:-cs}"
TAIL_LOGS="${TAIL_LOGS:-0}"
LOOKBACK_MINUTES="${LOOKBACK_MINUTES:-60}"
PRINT_RUN_REPORT="${PRINT_RUN_REPORT:-0}"

STATUS=0
fail() {
  local msg="$1"
  echo "FAIL: ${msg}" >&2
  STATUS=1
}

command -v aws >/dev/null 2>&1 || fail "aws CLI is required."
command -v jq >/dev/null 2>&1 || fail "jq is required for JSON parsing. Install via: brew install jq"

if [[ -z "${CLUSTER_ARN}" || -z "${TASK_FAMILY}" ]]; then
  fail "CLUSTER_ARN and TASK_FAMILY are required."
fi
if [[ -z "${SUBNET_IDS}" || -z "${SECURITY_GROUP_IDS}" ]]; then
  fail "SUBNET_IDS and SECURITY_GROUP_IDS are required for awsvpc."
fi
if [[ -z "${BUCKET}" ]]; then
  fail "BUCKET is required (or set JOBINTEL_S3_BUCKET)."
fi

if [[ "${STATUS}" -ne 0 ]]; then
  echo "Example: CLUSTER_ARN=... TASK_FAMILY=jobintel-daily REGION=us-east-1 SUBNET_IDS=subnet-1,subnet-2 SECURITY_GROUP_IDS=sg-1 BUCKET=... PREFIX=jobintel ./scripts/run_ecs_once.sh" >&2
  exit 2
fi

subnets_json=$(printf '%s' "${SUBNET_IDS}" | jq -R 'split(",") | map(gsub("^\\s+|\\s+$";"")) | map(select(length>0))')
sg_json=$(printf '%s' "${SECURITY_GROUP_IDS}" | jq -R 'split(",") | map(gsub("^\\s+|\\s+$";"")) | map(select(length>0))')

if [[ -n "${TASKDEF_ARN}" && -n "${TASKDEF_REV}" ]]; then
  fail "Set only one of TASKDEF_ARN or TASKDEF_REV."
fi

if [[ -n "${TASKDEF_ARN}" ]]; then
  TASK_DEF_ARN="${TASKDEF_ARN}"
elif [[ -n "${TASKDEF_REV}" ]]; then
  TASK_DEF_ARN="${TASK_FAMILY}:${TASKDEF_REV}"
else
  if [[ "${REQUIRE_LATEST_TASKDEF}" == "1" ]]; then
    TASK_DEF_ARN=$(aws ecs list-task-definitions \
      --family-prefix "${TASK_FAMILY}" \
      --sort DESC \
      --max-items 1 \
      --region "${REGION}" \
      --query 'taskDefinitionArns[0]' \
      --output text)
  else
    TASK_DEF_ARN="${TASK_FAMILY}"
  fi
fi

if [[ -z "${TASK_DEF_ARN}" || "${TASK_DEF_ARN}" == "None" ]]; then
  fail "No task definition found for family ${TASK_FAMILY}."
  echo "Summary:\nFAIL"; exit 1
fi

taskdef_desc=$(aws ecs describe-task-definition --task-definition "${TASK_DEF_ARN}" --region "${REGION}")
taskdef_image=$(printf '%s' "${taskdef_desc}" | jq -r '.taskDefinition.containerDefinitions[0].image // ""')

echo "Task definition: ${TASK_DEF_ARN}"
echo "Task image: ${taskdef_image:-unknown}"

# Run task
run_out=$(aws ecs run-task \
  --cluster "${CLUSTER_ARN}" \
  --launch-type FARGATE \
  --task-definition "${TASK_DEF_ARN}" \
  --network-configuration "awsvpcConfiguration={subnets=${subnets_json},securityGroups=${sg_json},assignPublicIp=ENABLED}" \
  --region "${REGION}")

task_arn=$(printf '%s' "${run_out}" | jq -r '.tasks[0].taskArn // ""')

if [[ -z "${task_arn}" ]]; then
  fail "Task failed to start (no taskArn)."
  echo "Summary:\nFAIL"; exit 1
fi

echo "Task ARN: ${task_arn}"

echo "Waiting for task to stop..."
aws ecs wait tasks-stopped --cluster "${CLUSTER_ARN}" --tasks "${task_arn}" --region "${REGION}" || true

desc=$(aws ecs describe-tasks --cluster "${CLUSTER_ARN}" --tasks "${task_arn}" --region "${REGION}")
exit_code=$(printf '%s' "${desc}" | jq -r '.tasks[0].containers[0].exitCode // "None"')
stopped_reason=$(printf '%s' "${desc}" | jq -r '.tasks[0].stoppedReason // ""')

pointer_status_global="not_found"
pointer_status_provider="not_found"

check_pointer() {
  local key="$1"
  local status="not_found"
  if aws s3api head-object --bucket "${BUCKET}" --key "${key}" --region "${REGION}" >/dev/null 2>&1; then
    status="ok"
  else
    err=$(
      aws s3api head-object --bucket "${BUCKET}" --key "${key}" --region "${REGION}" 2>&1 || true
    )
    if echo "${err}" | rg -qi "AccessDenied|403"; then
      status="access_denied"
    fi
  fi
  echo "${status}"
}

global_key="${PREFIX}/state/last_success.json"
provider_key="${PREFIX}/state/${PROVIDER}/${PROFILE}/last_success.json"
pointer_status_global=$(check_pointer "${global_key}")
pointer_status_provider=$(check_pointer "${provider_key}")

latest_run_id=$(aws s3api list-objects-v2 \
  --bucket "${BUCKET}" \
  --prefix "${PREFIX}/runs/" \
  --region "${REGION}" \
  --query "Contents[].Key" \
  --output json | \
  jq -r '.[]? | capture("/runs/(?<rid>[^/]+)/") | .rid' | sort | tail -n 1)

run_report_uri="s3://${BUCKET}/${PREFIX}/runs/${latest_run_id}/run_report.json"
run_report=$(aws s3 cp "${run_report_uri}" - 2>/dev/null || true)
echo "run_id: ${latest_run_id:-unknown}"
echo "run_report_uri: ${run_report_uri}"

baseline_resolved="no"
new_count="?"
changed_count="?"
removed_count="?"

if [[ -n "${run_report}" ]]; then
  echo "baseline_resolved: $(printf '%s' "${run_report}" | jq -r --arg p "${PROVIDER}" --arg pr "${PROFILE}" '.delta_summary.provider_profile[$p][$pr].baseline_resolved // false | if . then "yes" else "no" end')"
  echo "diff_counts: $(printf '%s' "${run_report}" | jq -r --arg p "${PROVIDER}" --arg pr "${PROFILE}" '[.delta_summary.provider_profile[$p][$pr].new_job_count, .changed_job_count, .removed_job_count] | join(" ")')"
fi

if [[ -n "${run_report}" ]]; then
  baseline_resolved=$(printf '%s' "${run_report}" | jq -r --arg p "${PROVIDER}" --arg pr "${PROFILE}" '.delta_summary.provider_profile[$p][$pr].baseline_resolved // false | if . then "yes" else "no" end')
  new_count=$(printf '%s' "${run_report}" | jq -r --arg p "${PROVIDER}" --arg pr "${PROFILE}" '.delta_summary.provider_profile[$p][$pr].new_job_count // "?"')
  changed_count=$(printf '%s' "${run_report}" | jq -r --arg p "${PROVIDER}" --arg pr "${PROFILE}" '.delta_summary.provider_profile[$p][$pr].changed_job_count // "?"')
  removed_count=$(printf '%s' "${run_report}" | jq -r --arg p "${PROVIDER}" --arg pr "${PROFILE}" '.delta_summary.provider_profile[$p][$pr].removed_job_count // "?"')
fi

if [[ "${exit_code}" != "0" && "${exit_code}" != "None" ]]; then
  fail "Task exit_code=${exit_code}"
fi

echo "pointer_status_global: ${pointer_status_global}"
echo "pointer_status_provider: ${pointer_status_provider}"
if [[ "${exit_code}" == "0" && "${S3_PUBLISH_REQUIRE:-0}" == "1" ]]; then
  if [[ "${pointer_status_global}" != "ok" || "${pointer_status_provider}" != "ok" ]]; then
    fail "Baseline pointers missing or inaccessible after successful run."
  fi
fi

if [[ "${baseline_resolved}" != "yes" ]]; then
  fail "Baseline not resolved for ${PROVIDER}/${PROFILE}."
fi

if [[ "${PRINT_RUN_REPORT}" == "1" ]]; then
  echo "\nrun_report_uri: ${run_report_uri}"
fi

if [[ "${TAIL_LOGS}" == "1" ]]; then
  if [[ -x "./scripts/cw_tail.sh" ]]; then
    FILTER=baseline LOOKBACK_MINUTES="${LOOKBACK_MINUTES}" REGION="${REGION}" ./scripts/cw_tail.sh || true
  else
    echo "WARN: scripts/cw_tail.sh not found or not executable."
  fi
fi

echo "\nVerdict:"
echo "exit_code: ${exit_code:-unknown}"
echo "stopped_reason: ${stopped_reason:-unknown}"
echo "baseline_resolved: ${baseline_resolved}"
echo "new/changed/removed: ${new_count}/${changed_count}/${removed_count}"
echo "pointer_written: ${pointer_written}"

echo "\nSummary:"
if [[ "${STATUS}" -eq 0 ]]; then
  echo "SUCCESS"
else
  echo "FAIL"
fi
exit "${STATUS}"
