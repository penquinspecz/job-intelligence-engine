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
command -v python3 >/dev/null 2>&1 || command -v python >/dev/null 2>&1 || fail "python3 (or python) is required."

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

task_def_arn=$(python3 - <<PY 2>/dev/null || python - <<PY
import json
import sys

data=json.loads("""${resp}""")
print(data.get("tasks", [{}])[0].get("taskDefinitionArn", ""))
PY
)

python3 - <<PY 2>/dev/null || python - <<PY
import json

data=json.loads("""${resp}""")

task=data.get("tasks", [{}])[0]
print("lastStatus:", task.get("lastStatus"))
print("stoppedReason:", task.get("stoppedReason"))
for container in task.get("containers", []):
    print("container:", container.get("name"))
    print("  exitCode:", container.get("exitCode"))
    print("  image:", container.get("image"))
    print("  imageDigest:", container.get("imageDigest"))
PY

if [[ -z "${task_def_arn}" ]]; then
  fail "Unable to resolve task definition ARN."
fi

taskdef=$(aws ecs describe-task-definition --task-definition "${task_def_arn}" --region "${REGION}" 2>/dev/null || true)
if [[ -z "${taskdef}" ]]; then
  fail "aws ecs describe-task-definition failed."
fi

python3 - <<PY 2>/dev/null || python - <<PY
import json

payload=json.loads("""${taskdef}""")
container=payload.get("taskDefinition", {}).get("containerDefinitions", [{}])[0]
print("taskDefinition:", payload.get("taskDefinition", {}).get("taskDefinitionArn"))
print("image:", container.get("image"))
print("environment:")
wanted={"S3_PUBLISH_ENABLED","S3_PUBLISH_REQUIRE","JOBINTEL_S3_BUCKET","JOBINTEL_S3_PREFIX"}
found=set()
for env in container.get("environment", []):
    name=env.get("name")
    if name in wanted:
        print(f"  {name}={env.get('value')}")
        found.add(name)
missing=sorted(wanted - found)
if missing:
    print("WARNING: missing env vars:", ", ".join(missing))
PY

if [[ -n "${EXPECT_IMAGE_SUBSTR}" ]]; then
  image=$(python3 - <<PY 2>/dev/null || python - <<PY
import json
payload=json.loads("""${taskdef}""")
container=payload.get("taskDefinition", {}).get("containerDefinitions", [{}])[0]
print(container.get("image", ""))
PY
)
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
