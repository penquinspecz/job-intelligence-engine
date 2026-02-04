#!/usr/bin/env bash
set -euo pipefail

AWS_REGION="${AWS_REGION:-${JOBINTEL_AWS_REGION:-}}"
AWS_ACCOUNT_ID="${AWS_ACCOUNT_ID:-}"
ECR_REPO="${ECR_REPO:-jobintel}"

if [ -z "$AWS_REGION" ]; then
  echo "ERROR: AWS_REGION (or JOBINTEL_AWS_REGION) is required" >&2
  exit 2
fi

if [ -z "$AWS_ACCOUNT_ID" ]; then
  AWS_ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "ERROR: docker is required" >&2
  exit 2
fi

if ! aws ecr describe-repositories --repository-names "$ECR_REPO" --region "$AWS_REGION" >/dev/null 2>&1; then
  aws ecr create-repository --repository-name "$ECR_REPO" --region "$AWS_REGION" >/dev/null
fi

aws ecr get-login-password --region "$AWS_REGION" \
  | docker login --username AWS --password-stdin "${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com" >/dev/null

git_sha="$(git rev-parse --short HEAD)"
image_repo="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${ECR_REPO}"
image_uri="${image_repo}:${git_sha}"

docker build -t "$image_uri" .
docker push "$image_uri" >/dev/null

echo "IMAGE_URI=${image_uri}"
