#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
EKS_DIR="${ROOT_DIR}/ops/aws/infra/eks"

TF_BIN="${TF_BIN:-}"
if [[ -z "${TF_BIN}" ]]; then
  if command -v tofu >/dev/null 2>&1; then
    TF_BIN="tofu"
  elif command -v terraform >/dev/null 2>&1; then
    TF_BIN="terraform"
  else
    echo "ERROR: neither tofu nor terraform is installed." >&2
    exit 2
  fi
fi

AWS_REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-us-east-1}}"
CLUSTER_NAME="${CLUSTER_NAME:-jobintel-eks}"

if [[ -z "${AWS_PROFILE:-}" ]]; then
  echo "ERROR: AWS_PROFILE is required for deterministic auth." >&2
  exit 2
fi

identity_json="$(aws sts get-caller-identity --output json --region "${AWS_REGION}")"
identity_arn="$(printf '%s' "${identity_json}" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("Arn", ""))')"
if [[ "${identity_arn}" == *":root" ]]; then
  echo "ERROR: refusing to run with root identity (${identity_arn})." >&2
  exit 2
fi

echo "AWS identity OK: ${identity_arn}"

if ! aws eks describe-cluster --name "${CLUSTER_NAME}" --region "${AWS_REGION}" --output json >/dev/null; then
  echo "ERROR: EKS cluster not found: ${CLUSTER_NAME} in ${AWS_REGION}" >&2
  exit 2
fi

echo "EKS cluster exists: ${CLUSTER_NAME}"

if ! "${TF_BIN}" -chdir="${EKS_DIR}" init -input=false -backend=false >/dev/null; then
  echo "ERROR: ${TF_BIN} init failed in ${EKS_DIR}." >&2
  exit 2
fi

state_list="$("${TF_BIN}" -chdir="${EKS_DIR}" state list 2>/dev/null || true)"
if [[ -z "${state_list}" ]]; then
  echo "STATE EMPTY: ${EKS_DIR} has no tracked resources." >&2
  cat >&2 <<EOF
To avoid creating duplicate infrastructure, stop here and import existing resources first.
Suggested starting imports (review before running):
  ${TF_BIN} -chdir=${EKS_DIR} import aws_eks_cluster.this ${CLUSTER_NAME}
  ${TF_BIN} -chdir=${EKS_DIR} import aws_eks_node_group.default ${CLUSTER_NAME}:${CLUSTER_NAME}-default
Then run:
  ${TF_BIN} -chdir=${EKS_DIR} state list
EOF
  exit 3
fi

if ! printf '%s\n' "${state_list}" | grep -qx 'aws_eks_cluster.this'; then
  echo "STATE MISALIGNED: state is non-empty but missing aws_eks_cluster.this" >&2
  echo "Refusing to continue. Reconcile imports before planning/applying." >&2
  exit 4
fi

state_cluster_name="$("${TF_BIN}" -chdir="${EKS_DIR}" state show aws_eks_cluster.this | awk -F' = ' '$1 ~ /^[[:space:]]*name$/ {print $2; exit}' | tr -d '"' | xargs || true)"
if [[ -z "${state_cluster_name}" ]]; then
  echo "STATE MISALIGNED: unable to read cluster name from state for aws_eks_cluster.this" >&2
  exit 4
fi

if [[ "${state_cluster_name}" != "${CLUSTER_NAME}" ]]; then
  echo "STATE MISMATCH: state cluster name is '${state_cluster_name}', expected '${CLUSTER_NAME}'" >&2
  echo "Refusing to continue to avoid creating another EKS cluster." >&2
  exit 4
fi

echo "State alignment OK: aws_eks_cluster.this name=${state_cluster_name}"
echo "Guardrails passed. Safe to run ${TF_BIN} plan/apply with local.auto.tfvars.json."
