#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 0 ]]; then
  echo "This script uses env vars only; no positional args are accepted." >&2
  echo "Example: BUCKET=<bucket> PREFIX=jobintel PROVIDER=openai PROFILE=cs ./scripts/verify_ops.sh" >&2
  exit 2
fi

BUCKET="${BUCKET:-${JOBINTEL_S3_BUCKET:-}}"
PREFIX="${PREFIX:-${JOBINTEL_S3_PREFIX:-jobintel}}"
PROVIDER="${PROVIDER:-openai}"
PROFILE="${PROFILE:-cs}"
REGION="${REGION:-${AWS_REGION:-us-east-1}}"

STATUS=0
fail() {
  local msg="$1"
  echo "FAIL: ${msg}" >&2
  STATUS=1
}

command -v aws >/dev/null 2>&1 || { fail "aws CLI is required."; }
command -v jq >/dev/null 2>&1 || { fail "jq is required for JSON parsing. Install via: brew install jq"; }

if [[ -z "${BUCKET}" ]]; then
  fail "BUCKET is required (or set JOBINTEL_S3_BUCKET)."
fi

if [[ "${STATUS}" -ne 0 ]]; then
  echo "Example: BUCKET=<bucket> PREFIX=jobintel PROVIDER=openai PROFILE=cs ./scripts/verify_ops.sh" >&2
  exit 2
fi

pretty_json() {
  jq .
}

missing_ptr=0

print_pointer() {
  local uri="$1"
  local label="$2"
  echo "\n${label}: ${uri}"
  if aws s3 ls "${uri}" >/dev/null 2>&1; then
    aws s3 cp "${uri}" - | pretty_json
  else
    echo "(missing)"
    missing_ptr=1
  fi
}

print_pointer "s3://${BUCKET}/${PREFIX}/state/last_success.json" "Global pointer"
print_pointer "s3://${BUCKET}/${PREFIX}/state/${PROVIDER}/${PROFILE}/last_success.json" "Provider pointer"

latest_run_id=$(aws s3api list-objects-v2 \
  --bucket "${BUCKET}" \
  --prefix "${PREFIX}/runs/" \
  --region "${REGION}" \
  --query "Contents[].Key" \
  --output json | \
  jq -r '.[]? | capture("/runs/(?<rid>[^/]+)/") | .rid' | sort | tail -n 1)

if [[ -z "${latest_run_id}" ]]; then
  echo "\nLatest run_id: (none)"
  fail "No runs found under s3://${BUCKET}/${PREFIX}/runs/."
  latest_run_id=""
fi

if [[ -n "${latest_run_id}" ]]; then
  echo "\nLatest run_id: ${latest_run_id}"
fi

run_report_uri="s3://${BUCKET}/${PREFIX}/runs/${latest_run_id}/run_report.json"
if [[ -n "${latest_run_id}" ]] && ! aws s3 ls "${run_report_uri}" >/dev/null 2>&1; then
  fail "run_report.json missing for latest run: ${run_report_uri}"
fi

run_report=""
if [[ -n "${latest_run_id}" ]]; then
  run_report=$(aws s3 cp "${run_report_uri}" - 2>/dev/null || true)
fi

if [[ -n "${run_report}" ]]; then
  echo "\nRun report summary:"
  echo "success: $(printf '%s' "${run_report}" | jq -r '.success')"
  echo "baseline_run_id: $(printf '%s' "${run_report}" | jq -r '.delta_summary.baseline_run_id')"
  echo "baseline_run_path: $(printf '%s' "${run_report}" | jq -r '.delta_summary.baseline_run_path')"
  diff_counts=$(printf '%s' "${run_report}" | jq -c --arg pr "${PROFILE}" '.diff_counts[$pr] // empty')
  if [[ -n "${diff_counts}" ]]; then
    echo "diff_counts[profile]: ${diff_counts}"
  else
    provider_diff=$(printf '%s' "${run_report}" | jq -c --arg p "${PROVIDER}" --arg pr "${PROFILE}" '.providers[$p].profiles[$pr].diff_counts // empty')
    if [[ -n "${provider_diff}" ]]; then
      echo "diff_counts[provider/profile]: ${provider_diff}"
    fi
  fi
  echo "provenance.live_http_status: $(printf '%s' "${run_report}" | jq -r --arg p "${PROVIDER}" '.provenance_by_provider[$p].live_http_status')"
  echo "provenance.live_status_code: $(printf '%s' "${run_report}" | jq -r --arg p "${PROVIDER}" '.provenance_by_provider[$p].live_status_code')"
  echo "provenance.scrape_mode: $(printf '%s' "${run_report}" | jq -r --arg p "${PROVIDER}" '.provenance_by_provider[$p].scrape_mode')"
  echo "provenance.unavailable_reason: $(printf '%s' "${run_report}" | jq -r --arg p "${PROVIDER}" '.provenance_by_provider[$p].unavailable_reason')"
  echo "provenance.error: $(printf '%s' "${run_report}" | jq -r --arg p "${PROVIDER}" '.provenance_by_provider[$p].error')"
fi

success=""
if [[ -n "${run_report}" ]]; then
  success=$(printf '%s' "${run_report}" | jq -r '.success')
fi

if [[ -n "${run_report}" && "${success}" != "True" && "${success}" != "true" ]]; then
  fail "Latest run is not successful."
fi

if [[ "${missing_ptr}" -ne 0 ]]; then
  fail "One or more baseline pointers are missing."
fi

echo "\nSummary:"
if [[ "${STATUS}" -eq 0 ]]; then
  echo "SUCCESS: pointers present and latest run successful."
else
  echo "FAIL: see messages above."
fi
exit "${STATUS}"
