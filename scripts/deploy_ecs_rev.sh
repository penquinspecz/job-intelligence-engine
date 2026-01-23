#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 0 ]]; then
  echo "This script uses env vars only; no positional args are accepted." >&2
  echo "Example: AWS_REGION=us-east-1 ./scripts/deploy_ecs_rev.sh" >&2
  exit 2
fi

AWS_REGION="${AWS_REGION:-us-east-1}"
ACCOUNT_ID="048622080012"
ECR_REPO="${ECR_REPO:-jobintel}"
ECR_URI="${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${ECR_REPO}"
INFRA_DIR="ops/aws/infra"

STATUS=0
fail() {
  local msg="$1"
  echo "FAIL: ${msg}" >&2
  STATUS=1
}

command -v git >/dev/null 2>&1 || fail "git is required."
command -v docker >/dev/null 2>&1 || fail "docker is required."
command -v aws >/dev/null 2>&1 || fail "aws CLI is required."
command -v jq >/dev/null 2>&1 || fail "jq is required. Install via: brew install jq"
command -v terraform >/dev/null 2>&1 || fail "terraform is required."

if [[ "${STATUS}" -ne 0 ]]; then
  exit 2
fi

GIT_SHA="$(git rev-parse --short HEAD)"
IMAGE_TAG="${ECR_URI}:${GIT_SHA}"

echo "Building image: ${IMAGE_TAG}"
docker build -t "${IMAGE_TAG}" .

echo "Logging into ECR: ${ECR_URI}"
aws ecr get-login-password --region "${AWS_REGION}" | \
  docker login --username AWS --password-stdin "${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"

echo "Pushing image: ${IMAGE_TAG}"
docker push "${IMAGE_TAG}"

echo "Applying Terraform with container_image=${IMAGE_TAG}"
(
  cd "${INFRA_DIR}"
  terraform init
  terraform apply -var="container_image=${IMAGE_TAG}"
)

TASK_DEF_ARN=$(aws ecs list-task-definitions \
  --family-prefix jobintel-daily \
  --sort DESC \
  --max-items 1 \
  --region "${AWS_REGION}" \
  --query 'taskDefinitionArns[0]' \
  --output text)

if [[ -z "${TASK_DEF_ARN}" || "${TASK_DEF_ARN}" == "None" ]]; then
  fail "Unable to resolve latest task definition ARN."
fi

echo "Task definition: ${TASK_DEF_ARN}"
echo "Summary: SUCCESS"
exit "${STATUS}"
