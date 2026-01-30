#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 0 ]]; then
  echo "This script uses env vars only; no positional args are accepted." >&2
  echo "Example: BUCKET=jobintel-prod1 PREFIX=jobintel RUN_ID=<run_id> ./scripts/verify_publish_s3.sh" >&2
  exit 2
fi

BUCKET="${JOBINTEL_S3_BUCKET:-${BUCKET:-}}"
PREFIX="${JOBINTEL_S3_PREFIX:-${PREFIX:-jobintel}}"
RUN_ID="${RUN_ID:-}"
REGION="${REGION:-${AWS_REGION:-us-east-1}}"
PROVIDER="${PROVIDER:-openai}"
PROFILE="${PROFILE:-cs}"

STATUS=0
fail() {
  local msg="$1"
  echo "FAIL: ${msg}" >&2
  STATUS=1
}
finish() {
  if [[ "${STATUS}" -eq 0 ]]; then
    echo "Summary: SUCCESS"
  else
    echo "Summary: FAIL"
  fi
  exit "${STATUS}"
}

command -v aws >/dev/null 2>&1 || fail "aws CLI is required."
command -v jq >/dev/null 2>&1 || fail "jq is required for JSON parsing. Install via: brew install jq"
if command -v shasum >/dev/null 2>&1; then
  SHA256_TOOL="shasum"
elif command -v sha256sum >/dev/null 2>&1; then
  SHA256_TOOL="sha256sum"
elif command -v python3 >/dev/null 2>&1; then
  SHA256_TOOL="python3"
else
  fail "sha256 hashing requires shasum, sha256sum, or python3."
fi

if [[ -z "${BUCKET}" || -z "${PREFIX}" ]]; then
  fail "BUCKET and PREFIX are required."
fi

prefix_clean="${PREFIX#/}"
prefix_clean="${prefix_clean%/}"
PREFIX="${prefix_clean}"

if [[ -z "${prefix_clean}" ]]; then
  fail "PREFIX must not be empty after normalization."
fi
if [[ "${STATUS}" -ne 0 ]]; then
  finish
fi

if [[ -z "${RUN_ID}" ]]; then
  command -v python3 >/dev/null 2>&1 || { fail "python3 is required to resolve run_id automatically. Set RUN_ID to bypass."; finish; }
  resolve_output=$(JOBINTEL_S3_BUCKET="${BUCKET}" JOBINTEL_S3_PREFIX="${prefix_clean}" PROVIDER="${PROVIDER}" PROFILE="${PROFILE}" REGION="${REGION}" \
    python3 scripts/resolve_s3_run_id.py 2>&1) || {
    fail "Unable to resolve run_id automatically: ${resolve_output}"
    finish
  }
  RUN_ID="${resolve_output}"
  if [[ -z "${RUN_ID}" ]]; then
    fail "Resolved empty run_id. Set RUN_ID explicitly to bypass automatic resolution."
    finish
  fi
fi

run_report_key="${prefix_clean}/runs/${RUN_ID}/run_report.json"
ranked_key="${prefix_clean}/runs/${RUN_ID}/${PROVIDER}/${PROFILE}/${PROVIDER}_ranked_families.${PROFILE}.json"
latest_prefix="${prefix_clean}/latest/${PROVIDER}/${PROFILE}/"

head_object() {
  local key="$1"
  aws s3api head-object --bucket "${BUCKET}" --key "${key}" --region "${REGION}" --query ContentType --output text 2>/dev/null
}

list_keys() {
  local key_prefix="$1"
  aws s3api list-objects-v2 \
    --bucket "${BUCKET}" \
    --prefix "${key_prefix}" \
    --region "${REGION}" \
    --query "Contents[].Key" \
    --output json 2>/dev/null || true
}

require_object() {
  local key="$1"
  if ! head_object "${key}" >/dev/null; then
    fail "Missing s3://${BUCKET}/${key}"
    return 1
  fi
  return 0
}

latest_has_artifacts="no"

if ! require_object "${run_report_key}"; then
  finish
fi

if ! head_object "${ranked_key}" >/dev/null; then
  fail "Missing ranked artifacts at s3://${BUCKET}/${ranked_key}"
fi

if head_object "${latest_prefix}run_report.json" >/dev/null; then
  latest_has_artifacts="yes"
else
  latest_keys_json=$(list_keys "${latest_prefix}")
  latest_key=$(printf '%s' "${latest_keys_json}" | jq -r '.[]?' | head -n 1)
  if [[ -n "${latest_key}" ]]; then
    latest_has_artifacts="yes"
  else
    fail "Missing latest artifacts under s3://${BUCKET}/${latest_prefix}"
  fi
fi

tmp_dir=$(mktemp -d)
trap 'rm -rf "${tmp_dir}"' EXIT

download_and_print() {
  local key="$1"
  local label="$2"
  local out_path="${tmp_dir}/$(basename "${key}")"
  aws s3 cp "s3://${BUCKET}/${key}" "${out_path}" --region "${REGION}" >/dev/null 2>&1 || {
    fail "Failed to download s3://${BUCKET}/${key}"
    return
  }
  local ctype
  ctype=$(head_object "${key}" || echo "unknown")
  local sha
  case "${SHA256_TOOL}" in
    shasum)
      sha=$(shasum -a 256 "${out_path}" | awk '{print $1}')
      ;;
    sha256sum)
      sha=$(sha256sum "${out_path}" | awk '{print $1}')
      ;;
    python3)
      sha=$(python3 -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "${out_path}")
      ;;
  esac
  echo "${label}: key=${key} content_type=${ctype} sha256=${sha}"
}

download_and_print "${run_report_key}" "run_report"
download_and_print "${ranked_key}" "ranked_artifact"

run_report_ct=$(head_object "${run_report_key}" || echo "unknown")
if [[ "${run_report_ct}" != "application/json" ]]; then
  fail "run_report.json content-type mismatch: ${run_report_ct}"
fi
ranked_ct=$(head_object "${ranked_key}" || echo "unknown")
if [[ "${ranked_ct}" != "application/json" ]]; then
  fail "ranked artifact content-type mismatch: ${ranked_ct}"
fi

finish
