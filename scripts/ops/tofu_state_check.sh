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
    echo "ERROR: neither tofu nor terraform is installed" >&2
    exit 2
  fi
fi

AWS_REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-us-east-1}}"
CLUSTER_NAME="${CLUSTER_NAME:-jobintel-eks}"

print_header() {
  echo "== $1 =="
}

print_header "OpenTofu backend summary"
backend_line="$(rg -n 'backend\s+"[^"]+"' "${EKS_DIR}" -g '*.tf' || true)"
if [[ -z "${backend_line}" ]]; then
  echo "Backend config: none in ${EKS_DIR}/*.tf"
  echo "Backend type: local (default)"
else
  echo "Backend blocks:"
  echo "${backend_line}"
  backend_type="$(printf '%s\n' "${backend_line}" | sed -E 's/.*backend\s+"([^"]+)".*/\1/' | paste -sd ',' -)"
  echo "Backend type(s): ${backend_type}"
fi

echo
print_header "Workspace"
workspace="$("${TF_BIN}" -chdir="${EKS_DIR}" workspace show 2>/dev/null || echo '<unknown>')"
echo "Current workspace: ${workspace}"
"${TF_BIN}" -chdir="${EKS_DIR}" workspace list 2>/dev/null || true

echo
print_header "State"
state_list="$("${TF_BIN}" -chdir="${EKS_DIR}" state list 2>/tmp/tofu_state_check_state.err || true)"
if [[ -z "${state_list}" ]]; then
  err_msg="$(cat /tmp/tofu_state_check_state.err 2>/dev/null || true)"
  echo "State status: EMPTY"
  if [[ -n "${err_msg}" ]]; then
    echo "state list message:"
    echo "${err_msg}" | sed 's/^/  /'
  fi
else
  echo "State status: NON-EMPTY"
  echo "Managed resources:"
  printf '%s\n' "${state_list}" | sed 's/^/  - /'
fi

has_cluster_in_state="no"
if printf '%s\n' "${state_list}" | grep -qx 'aws_eks_cluster.this'; then
  has_cluster_in_state="yes"
fi

echo
print_header "AWS cluster check"
cluster_exists="unknown"
cluster_check_msg=""
if ! command -v aws >/dev/null 2>&1; then
  cluster_check_msg="aws CLI not found"
elif [[ -z "${AWS_PROFILE:-}" ]]; then
  cluster_check_msg="AWS_PROFILE is unset"
else
  if aws eks describe-cluster --name "${CLUSTER_NAME}" --region "${AWS_REGION}" --output json >/tmp/tofu_state_check_cluster.json 2>/tmp/tofu_state_check_cluster.err; then
    cluster_exists="yes"
    cluster_status="$(aws eks describe-cluster --name "${CLUSTER_NAME}" --region "${AWS_REGION}" --query 'cluster.status' --output text 2>/dev/null || echo '<unknown>')"
    cluster_check_msg="cluster exists (${cluster_status})"
  else
    cluster_exists="no"
    cluster_check_msg="$(cat /tmp/tofu_state_check_cluster.err 2>/dev/null || true)"
  fi
fi

echo "AWS_PROFILE=${AWS_PROFILE:-<unset>}"
echo "AWS_REGION=${AWS_REGION}"
echo "CLUSTER_NAME=${CLUSTER_NAME}"
echo "Cluster exists: ${cluster_exists}"
if [[ -n "${cluster_check_msg}" ]]; then
  echo "Cluster check message: ${cluster_check_msg}"
fi

echo
print_header "Recommended next command"
if [[ -n "${state_list}" && "${has_cluster_in_state}" == "yes" ]]; then
  echo "State appears aligned enough for planning."
  echo "Run: ${TF_BIN} -chdir=${EKS_DIR} plan -input=false -var-file=local.auto.tfvars.json"
elif [[ -z "${state_list}" && "${cluster_exists}" == "yes" ]]; then
  echo "Cluster exists but state is empty. Import existing resources before planning/applying."
  echo "Run: DO_IMPORT=1 CLUSTER_NAME=${CLUSTER_NAME} AWS_REGION=${AWS_REGION} AWS_PROFILE=${AWS_PROFILE:-jobintel-deployer} scripts/ops/tofu_state_check.sh --print-imports"
else
  echo "State/cluster status is ambiguous. Verify AWS identity/backend/workspace before any apply."
  echo "Run: AWS_PROFILE=<profile> AWS_REGION=${AWS_REGION} CLUSTER_NAME=${CLUSTER_NAME} scripts/ops/tofu_state_check.sh"
fi

if [[ "${1:-}" == "--print-imports" ]]; then
  echo
  print_header "Deterministic import plan (preview)"

  oidc_issuer="$(aws eks describe-cluster --name "${CLUSTER_NAME}" --region "${AWS_REGION}" --query 'cluster.identity.oidc.issuer' --output text 2>/dev/null || true)"
  oidc_host="${oidc_issuer#https://}"
  oidc_arn_cmd="aws iam list-open-id-connect-providers --query \"OpenIDConnectProviderList[].Arn\" --output text | tr '\\t' '\\n' | while read -r arn; do aws iam get-open-id-connect-provider --open-id-connect-provider-arn \"\$arn\" --query Url --output text | grep -qx \"${oidc_host}\" && echo \"\$arn\" && break; done"

  cat <<EOF
${TF_BIN} -chdir=${EKS_DIR} import aws_iam_role.eks_cluster ${CLUSTER_NAME}-cluster-role
${TF_BIN} -chdir=${EKS_DIR} import aws_iam_role_policy_attachment.eks_cluster_policy ${CLUSTER_NAME}-cluster-role/arn:aws:iam::aws:policy/AmazonEKSClusterPolicy
${TF_BIN} -chdir=${EKS_DIR} import aws_iam_role_policy_attachment.eks_service_policy ${CLUSTER_NAME}-cluster-role/arn:aws:iam::aws:policy/AmazonEKSServicePolicy
${TF_BIN} -chdir=${EKS_DIR} import aws_eks_cluster.this ${CLUSTER_NAME}
${TF_BIN} -chdir=${EKS_DIR} import aws_iam_role.node ${CLUSTER_NAME}-node-role
${TF_BIN} -chdir=${EKS_DIR} import aws_iam_role_policy_attachment.node_worker ${CLUSTER_NAME}-node-role/arn:aws:iam::aws:policy/AmazonEKSWorkerNodePolicy
${TF_BIN} -chdir=${EKS_DIR} import aws_iam_role_policy_attachment.node_cni ${CLUSTER_NAME}-node-role/arn:aws:iam::aws:policy/AmazonEKS_CNI_Policy
${TF_BIN} -chdir=${EKS_DIR} import aws_iam_role_policy_attachment.node_ecr ${CLUSTER_NAME}-node-role/arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly
${TF_BIN} -chdir=${EKS_DIR} import aws_eks_node_group.default ${CLUSTER_NAME}:${CLUSTER_NAME}-default
${TF_BIN} -chdir=${EKS_DIR} import aws_iam_openid_connect_provider.this "\$(${oidc_arn_cmd})"
${TF_BIN} -chdir=${EKS_DIR} import aws_iam_role.jobintel_irsa ${CLUSTER_NAME}-jobintel-irsa
${TF_BIN} -chdir=${EKS_DIR} import aws_iam_policy.jobintel_s3 "\$(aws iam list-policies --scope Local --query \"Policies[?PolicyName=='${CLUSTER_NAME}-jobintel-s3'].Arn | [0]\" --output text)"
${TF_BIN} -chdir=${EKS_DIR} import aws_iam_role_policy_attachment.jobintel_s3 ${CLUSTER_NAME}-jobintel-irsa/\$(aws iam list-policies --scope Local --query \"Policies[?PolicyName=='${CLUSTER_NAME}-jobintel-s3'].Arn | [0]\" --output text)
for subnet_id in \$(aws eks describe-cluster --name "${CLUSTER_NAME}" --region "${AWS_REGION}" --query 'cluster.resourcesVpcConfig.subnetIds[]' --output text); do
  ${TF_BIN} -chdir=${EKS_DIR} import "aws_ec2_tag.subnet_cluster[\"\${subnet_id}\"]" "\${subnet_id},kubernetes.io/cluster/${CLUSTER_NAME}"
done
EOF

  echo
  if [[ "${DO_IMPORT:-0}" == "1" ]]; then
    echo "DO_IMPORT=1 set. Executing import plan now."
    eval "${TF_BIN} -chdir=${EKS_DIR} import aws_iam_role.eks_cluster ${CLUSTER_NAME}-cluster-role"
    eval "${TF_BIN} -chdir=${EKS_DIR} import aws_iam_role_policy_attachment.eks_cluster_policy ${CLUSTER_NAME}-cluster-role/arn:aws:iam::aws:policy/AmazonEKSClusterPolicy"
    eval "${TF_BIN} -chdir=${EKS_DIR} import aws_iam_role_policy_attachment.eks_service_policy ${CLUSTER_NAME}-cluster-role/arn:aws:iam::aws:policy/AmazonEKSServicePolicy"
    eval "${TF_BIN} -chdir=${EKS_DIR} import aws_eks_cluster.this ${CLUSTER_NAME}"
    eval "${TF_BIN} -chdir=${EKS_DIR} import aws_iam_role.node ${CLUSTER_NAME}-node-role"
    eval "${TF_BIN} -chdir=${EKS_DIR} import aws_iam_role_policy_attachment.node_worker ${CLUSTER_NAME}-node-role/arn:aws:iam::aws:policy/AmazonEKSWorkerNodePolicy"
    eval "${TF_BIN} -chdir=${EKS_DIR} import aws_iam_role_policy_attachment.node_cni ${CLUSTER_NAME}-node-role/arn:aws:iam::aws:policy/AmazonEKS_CNI_Policy"
    eval "${TF_BIN} -chdir=${EKS_DIR} import aws_iam_role_policy_attachment.node_ecr ${CLUSTER_NAME}-node-role/arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly"
    eval "${TF_BIN} -chdir=${EKS_DIR} import aws_eks_node_group.default ${CLUSTER_NAME}:${CLUSTER_NAME}-default"
    eval "${TF_BIN} -chdir=${EKS_DIR} import aws_iam_openid_connect_provider.this \"$(${oidc_arn_cmd})\""
    eval "${TF_BIN} -chdir=${EKS_DIR} import aws_iam_role.jobintel_irsa ${CLUSTER_NAME}-jobintel-irsa"
    eval "${TF_BIN} -chdir=${EKS_DIR} import aws_iam_policy.jobintel_s3 \"$(aws iam list-policies --scope Local --query \"Policies[?PolicyName=='${CLUSTER_NAME}-jobintel-s3'].Arn | [0]\" --output text)\""
    eval "${TF_BIN} -chdir=${EKS_DIR} import aws_iam_role_policy_attachment.jobintel_s3 ${CLUSTER_NAME}-jobintel-irsa/$(aws iam list-policies --scope Local --query \"Policies[?PolicyName=='${CLUSTER_NAME}-jobintel-s3'].Arn | [0]\" --output text)"
    while read -r subnet_id; do
      [[ -z "${subnet_id}" ]] && continue
      eval "${TF_BIN} -chdir=${EKS_DIR} import \"aws_ec2_tag.subnet_cluster[\\\"${subnet_id}\\\"]\" \"${subnet_id},kubernetes.io/cluster/${CLUSTER_NAME}\""
    done < <(aws eks describe-cluster --name "${CLUSTER_NAME}" --region "${AWS_REGION}" --query 'cluster.resourcesVpcConfig.subnetIds[]' --output text | tr '\t' '\n')
  else
    echo "DO_IMPORT is not set to 1. Preview only; no imports executed."
  fi
fi
