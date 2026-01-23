#!/usr/bin/env bash
set -euo pipefail

# Usage (env only):
#   CLUSTER_ARN=... TASK_ARN=... REGION=us-east-1 ./scripts/ecs_verify_task.sh
#   EXPECT_IMAGE_SUBSTR=jobintel CLUSTER_ARN=... TASK_ARN=... ./scripts/ecs_verify_task.sh

CLUSTER_ARN="${CLUSTER_ARN:-}"
TASK_ARN="${TASK_ARN:-}"
REGION="${REGION:-${AWS_REGION:-us-east-1}}"
EXPECT_IMAGE_SUBSTR="${EXPECT_IMAGE_SUBSTR:-}"

if [[ $# -ne 0 ]]; then
  echo "This script uses env vars only; no positional args are accepted." >&2
  echo "Example: CLUSTER_ARN=... TASK_ARN=... REGION=us-east-1 ./scripts/ecs_verify_task.sh" >&2
  exit 2
fi

STATUS=0
fail() {
  local msg="$1"
  echo "FAIL: ${msg}" >&2
  STATUS=1
}

command -v aws >/dev/null 2>&1 || fail "aws CLI is required."
command -v jq >/dev/null 2>&1 || fail "jq is required for JSON parsing. Install via: brew install jq"

if [[ -z "${CLUSTER_ARN}" || -z "${TASK_ARN}" ]]; then
  fail "CLUSTER_ARN and TASK_ARN are required."
fi

if [[ "${STATUS}" -ne 0 ]]; then
  echo "Example: CLUSTER_ARN=... TASK_ARN=... REGION=us-east-1 ./scripts/ecs_verify_task.sh" >&2
  exit 2
fi

resp=$(aws ecs describe-tasks --cluster "${CLUSTER_ARN}" --tasks "${TASK_ARN}" --region "${REGION}" 2>/dev/null || true)
if [[ -z "${resp}" ]]; then
  fail "aws ecs describe-tasks failed."
fi

task_def_arn=$(printf '%s' "${resp}" | jq -r '.tasks[0].taskDefinitionArn // ""')

printf '%s' "${resp}" | jq -r '
  .tasks[0] as $t |
  "lastStatus: \($t.lastStatus)",
  "stoppedReason: \($t.stoppedReason)",
  ($t.containers[]? | "container: \(.name)\n  exitCode: \(.exitCode)\n  image: \(.image)\n  imageDigest: \(.imageDigest)")
'

if [[ -z "${task_def_arn}" ]]; then
  fail "Unable to resolve task definition ARN."
fi

taskdef=$(aws ecs describe-task-definition --task-definition "${task_def_arn}" --region "${REGION}" 2>/dev/null || true)
if [[ -z "${taskdef}" ]]; then
  fail "aws ecs describe-task-definition failed."
fi

printf '%s' "${taskdef}" | jq -r '
  .taskDefinition as $td |
  "taskDefinition: \($td.taskDefinitionArn)",
  "image: \($td.containerDefinitions[0].image // "")",
  "environment:",
  ($td.containerDefinitions[0].environment // [] | map(select(.name == "S3_PUBLISH_ENABLED" or .name == "S3_PUBLISH_REQUIRE" or .name == "JOBINTEL_S3_BUCKET" or .name == "JOBINTEL_S3_PREFIX")) | .[] | "  \(.name)=\(.value)")
'
missing_envs=$(printf '%s' "${taskdef}" | jq -r '
  .taskDefinition.containerDefinitions[0].environment // [] |
  map(.name) as $names |
  ["S3_PUBLISH_ENABLED","S3_PUBLISH_REQUIRE","JOBINTEL_S3_BUCKET","JOBINTEL_S3_PREFIX"] |
  map(select(. as $n | ($names | index($n)) == null)) |
  join(",")
')
if [[ -n "${missing_envs}" ]]; then
  echo "WARNING: missing env vars: ${missing_envs}"
fi

if [[ -n "${EXPECT_IMAGE_SUBSTR}" ]]; then
  image=$(printf '%s' "${taskdef}" | jq -r '.taskDefinition.containerDefinitions[0].image // ""')
  if [[ "${image}" != *"${EXPECT_IMAGE_SUBSTR}"* ]]; then
    echo "WARNING: image does not match expected substring: ${EXPECT_IMAGE_SUBSTR}" >&2
  fi
fi

echo "\nSummary:"
if [[ "${STATUS}" -eq 0 ]]; then
  echo "SUCCESS: ECS task inspected."
else
  echo "FAIL: see messages above."
fi
exit "${STATUS}"
