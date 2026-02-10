#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="${TOFU_STATE_CHECK_ROOT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
EKS_DIR="${ROOT_DIR}/ops/aws/infra/eks"
AWS_REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-us-east-1}}"
CLUSTER_NAME="${CLUSTER_NAME:-jobintel-eks}"
RUN_ID="${RUN_ID:-local}"
BUNDLE_DIR="${ROOT_DIR}/ops/proof/bundles/m4-${RUN_ID}/eks_infra"
IMPORT_SCRIPT_PATH="${BUNDLE_DIR}/import.sh"

PRINT_IMPORTS=0
RUN_IMPORTS=0

for arg in "$@"; do
  case "$arg" in
    --print-imports)
      PRINT_IMPORTS=1
      ;;
    --run-imports)
      RUN_IMPORTS=1
      ;;
    *)
      echo "ERROR: unknown arg: ${arg}" >&2
      echo "NEXT: scripts/ops/tofu_state_check.sh [--print-imports] [--run-imports]" >&2
      exit 2
      ;;
  esac
done

fail_with_next() {
  local message="$1"
  local next_cmd="$2"
  echo "ERROR: ${message}" >&2
  echo "NEXT: ${next_cmd}" >&2
  exit 2
}

TF_BIN="${TF_BIN:-}"
if [[ -z "${TF_BIN}" ]]; then
  if command -v tofu >/dev/null 2>&1; then
    TF_BIN="tofu"
  elif command -v terraform >/dev/null 2>&1; then
    TF_BIN="terraform"
  else
    fail_with_next \
      "neither tofu nor terraform is installed" \
      "brew install opentofu"
  fi
fi

print_header() {
  echo "== $1 =="
}

write_import_script() {
  mkdir -p "${BUNDLE_DIR}"

  cat >"${IMPORT_SCRIPT_PATH}" <<EOF
#!/usr/bin/env bash
set -euo pipefail

if [[ "\${DO_IMPORT:-0}" != "1" ]]; then
  echo "ERROR: DO_IMPORT=1 is required to run imports." >&2
  echo "NEXT: DO_IMPORT=1 bash ${IMPORT_SCRIPT_PATH}" >&2
  exit 2
fi

TF_BIN="${TF_BIN}"
EKS_DIR="${EKS_DIR}"
AWS_REGION="${AWS_REGION}"
CLUSTER_NAME="${CLUSTER_NAME}"

oidc_issuer="\$(aws eks describe-cluster --name "\${CLUSTER_NAME}" --region "\${AWS_REGION}" --query 'cluster.identity.oidc.issuer' --output text)"
oidc_host="\${oidc_issuer#https://}"
oidc_arn="\$(aws iam list-open-id-connect-providers --query 'OpenIDConnectProviderList[].Arn' --output text | tr '\\t' '\\n' | while read -r arn; do aws iam get-open-id-connect-provider --open-id-connect-provider-arn "\$arn" --query Url --output text | grep -qx "\${oidc_host}" && echo "\$arn" && break; done)"
policy_arn="\$(aws iam list-policies --scope Local --query "Policies[?PolicyName=='\${CLUSTER_NAME}-jobintel-s3'].Arn | [0]" --output text)"

"\${TF_BIN}" -chdir="\${EKS_DIR}" import aws_iam_role.eks_cluster "\${CLUSTER_NAME}-cluster-role"
"\${TF_BIN}" -chdir="\${EKS_DIR}" import aws_iam_role_policy_attachment.eks_cluster_policy "\${CLUSTER_NAME}-cluster-role/arn:aws:iam::aws:policy/AmazonEKSClusterPolicy"
"\${TF_BIN}" -chdir="\${EKS_DIR}" import aws_iam_role_policy_attachment.eks_service_policy "\${CLUSTER_NAME}-cluster-role/arn:aws:iam::aws:policy/AmazonEKSServicePolicy"
"\${TF_BIN}" -chdir="\${EKS_DIR}" import aws_eks_cluster.this "\${CLUSTER_NAME}"
"\${TF_BIN}" -chdir="\${EKS_DIR}" import aws_iam_role.node "\${CLUSTER_NAME}-node-role"
"\${TF_BIN}" -chdir="\${EKS_DIR}" import aws_iam_role_policy_attachment.node_worker "\${CLUSTER_NAME}-node-role/arn:aws:iam::aws:policy/AmazonEKSWorkerNodePolicy"
"\${TF_BIN}" -chdir="\${EKS_DIR}" import aws_iam_role_policy_attachment.node_cni "\${CLUSTER_NAME}-node-role/arn:aws:iam::aws:policy/AmazonEKS_CNI_Policy"
"\${TF_BIN}" -chdir="\${EKS_DIR}" import aws_iam_role_policy_attachment.node_ecr "\${CLUSTER_NAME}-node-role/arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly"
"\${TF_BIN}" -chdir="\${EKS_DIR}" import aws_eks_node_group.default "\${CLUSTER_NAME}:\${CLUSTER_NAME}-default"
"\${TF_BIN}" -chdir="\${EKS_DIR}" import aws_iam_openid_connect_provider.this "\${oidc_arn}"
"\${TF_BIN}" -chdir="\${EKS_DIR}" import aws_iam_role.jobintel_irsa "\${CLUSTER_NAME}-jobintel-irsa"
"\${TF_BIN}" -chdir="\${EKS_DIR}" import aws_iam_policy.jobintel_s3 "\${policy_arn}"
"\${TF_BIN}" -chdir="\${EKS_DIR}" import aws_iam_role_policy_attachment.jobintel_s3 "\${CLUSTER_NAME}-jobintel-irsa/\${policy_arn}"

mapfile -t subnet_ids < <(aws eks describe-cluster --name "\${CLUSTER_NAME}" --region "\${AWS_REGION}" --query 'cluster.resourcesVpcConfig.subnetIds[]' --output text | tr '\\t' '\\n' | sed '/^$/d' | LC_ALL=C sort)
for subnet_id in "\${subnet_ids[@]}"; do
  "\${TF_BIN}" -chdir="\${EKS_DIR}" import "aws_ec2_tag.subnet_cluster[\"\${subnet_id}\"]" "\${subnet_id},kubernetes.io/cluster/\${CLUSTER_NAME}"
done

echo "Imports complete."
echo "NEXT: \${TF_BIN} -chdir=\${EKS_DIR} state list"
echo "NEXT: \${TF_BIN} -chdir=\${EKS_DIR} plan -input=false -var-file=local.auto.tfvars.json"
EOF

  chmod +x "${IMPORT_SCRIPT_PATH}"
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
state_err_file="$(mktemp)"
state_list="$("${TF_BIN}" -chdir="${EKS_DIR}" state list 2>"${state_err_file}" || true)"
if [[ -z "${state_list}" ]]; then
  err_msg="$(cat "${state_err_file}" 2>/dev/null || true)"
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
rm -f "${state_err_file}"

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
  cluster_check_file="$(mktemp)"
  if aws eks describe-cluster --name "${CLUSTER_NAME}" --region "${AWS_REGION}" --output json >"${cluster_check_file}" 2>/dev/null; then
    cluster_exists="yes"
    cluster_status="$(aws eks describe-cluster --name "${CLUSTER_NAME}" --region "${AWS_REGION}" --query 'cluster.status' --output text 2>/dev/null || echo '<unknown>')"
    cluster_check_msg="cluster exists (${cluster_status})"
  else
    cluster_exists="no"
    cluster_check_msg="cluster not found or inaccessible"
  fi
  rm -f "${cluster_check_file}"
fi

echo "AWS_PROFILE=${AWS_PROFILE:-<unset>}"
echo "AWS_REGION=${AWS_REGION}"
echo "CLUSTER_NAME=${CLUSTER_NAME}"
echo "Cluster exists: ${cluster_exists}"
if [[ -n "${cluster_check_msg}" ]]; then
  echo "Cluster check message: ${cluster_check_msg}"
fi

if [[ "${PRINT_IMPORTS}" == "1" ]]; then
  write_import_script
  echo
  print_header "Deterministic import plan"
  echo "Import script generated: ${IMPORT_SCRIPT_PATH}"
  echo "Preview commands:"
  sed 's/^/  /' "${IMPORT_SCRIPT_PATH}"
  echo "NEXT: Review ${IMPORT_SCRIPT_PATH}"
  echo "NEXT: DO_IMPORT=1 bash ${IMPORT_SCRIPT_PATH}"
fi

echo
print_header "Recommended next command"
if [[ -n "${state_list}" && "${has_cluster_in_state}" == "yes" ]]; then
  echo "State appears aligned enough for planning."
  echo "Run: ${TF_BIN} -chdir=${EKS_DIR} plan -input=false -var-file=local.auto.tfvars.json"
elif [[ -z "${state_list}" && "${cluster_exists}" == "yes" ]]; then
  echo "Cluster exists but state is empty. Import existing resources before planning/applying."
  echo "Run: AWS_PROFILE=${AWS_PROFILE:-jobintel-deployer} AWS_REGION=${AWS_REGION} CLUSTER_NAME=${CLUSTER_NAME} RUN_ID=${RUN_ID} scripts/ops/tofu_state_check.sh --print-imports"
  echo "Then: DO_IMPORT=1 bash ${IMPORT_SCRIPT_PATH}"
else
  echo "State/cluster status is ambiguous. Verify AWS identity/backend/workspace before any apply."
  echo "Run: AWS_PROFILE=<profile> AWS_REGION=${AWS_REGION} CLUSTER_NAME=${CLUSTER_NAME} scripts/ops/tofu_state_check.sh"
fi

if [[ "${RUN_IMPORTS}" == "1" ]]; then
  if [[ ! -f "${IMPORT_SCRIPT_PATH}" ]]; then
    fail_with_next \
      "import script not found: ${IMPORT_SCRIPT_PATH}" \
      "AWS_PROFILE=${AWS_PROFILE:-jobintel-deployer} AWS_REGION=${AWS_REGION} CLUSTER_NAME=${CLUSTER_NAME} RUN_ID=${RUN_ID} scripts/ops/tofu_state_check.sh --print-imports"
  fi
  if [[ "${DO_IMPORT:-0}" != "1" ]]; then
    fail_with_next \
      "DO_IMPORT must be 1 before running imports" \
      "DO_IMPORT=1 bash ${IMPORT_SCRIPT_PATH}"
  fi

  echo "Executing reviewed import script: ${IMPORT_SCRIPT_PATH}"
  bash "${IMPORT_SCRIPT_PATH}"
fi
