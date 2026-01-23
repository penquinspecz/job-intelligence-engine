#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 0 ]]; then
  echo "This script uses env vars only; no positional args are accepted." >&2
  echo "Example: TASKDEF_REV=3 AWS_REGION=us-east-1 ./scripts/print_taskdef_env.sh" >&2
  exit 2
fi

AWS_REGION="${AWS_REGION:-us-east-1}"
TASKDEF_ARN="${TASKDEF_ARN:-}"
TASKDEF_REV="${TASKDEF_REV:-}"
TASK_FAMILY="${TASK_FAMILY:-jobintel-daily}"

STATUS=0
fail() {
  local msg="$1"
  echo "FAIL: ${msg}" >&2
  STATUS=1
}

command -v aws >/dev/null 2>&1 || fail "aws CLI is required."
command -v jq >/dev/null 2>&1 || fail "jq is required. Install via: brew install jq"

if [[ -n "${TASKDEF_ARN}" && -n "${TASKDEF_REV}" ]]; then
  fail "Set only one of TASKDEF_ARN or TASKDEF_REV."
fi

if [[ -z "${TASKDEF_ARN}" ]]; then
  if [[ -n "${TASKDEF_REV}" ]]; then
    TASKDEF_ARN="${TASK_FAMILY}:${TASKDEF_REV}"
  else
    TASKDEF_ARN="${TASK_FAMILY}"
  fi
fi

if [[ "${STATUS}" -ne 0 ]]; then
  exit 2
fi

taskdef=$(aws ecs describe-task-definition --task-definition "${TASKDEF_ARN}" --region "${AWS_REGION}" 2>/dev/null || true)
if [[ -z "${taskdef}" ]]; then
  fail "aws ecs describe-task-definition failed for ${TASKDEF_ARN}"
  exit 2
fi

printf '%s\n' "${taskdef}" | jq -r '
  .taskDefinition as $td |
  "taskDefinition: \($td.taskDefinitionArn)",
  "image: \($td.containerDefinitions[0].image // "")",
  "environment:",
  ($td.containerDefinitions[0].environment // [] |
    map(select(.name == "S3_PUBLISH_ENABLED" or .name == "S3_PUBLISH_REQUIRE" or .name == "JOBINTEL_S3_BUCKET" or .name == "JOBINTEL_S3_PREFIX")) |
    .[] | "  \(.name)=\(.value)")
'

exit "${STATUS}"
