#!/usr/bin/env bash
set -euo pipefail

BUCKET="${BUCKET:-${JOBINTEL_S3_BUCKET:-}}"
PREFIX="${PREFIX:-${JOBINTEL_S3_PREFIX:-jobintel}}"
PROVIDER="${PROVIDER:-openai}"
PROFILE="${PROFILE:-cs}"
command -v jq >/dev/null 2>&1 || { echo "jq is required. Install via: brew install jq" >&2; exit 2; }

if [[ -z "${BUCKET}" ]]; then
  echo "BUCKET is required (or set JOBINTEL_S3_BUCKET)." >&2
  exit 2
fi

echo "Bucket: ${BUCKET}"
echo "Prefix: ${PREFIX}"
echo "Provider/Profile: ${PROVIDER}/${PROFILE}"

echo "\nState keys:"
aws s3 ls "s3://${BUCKET}/${PREFIX}/state/" || true
aws s3 ls "s3://${BUCKET}/${PREFIX}/state/${PROVIDER}/${PROFILE}/" || true

echo "\nGlobal pointer (state/last_success.json):"
if ! aws s3 cp "s3://${BUCKET}/${PREFIX}/state/last_success.json" - 2>/dev/null; then
  echo "(missing)"
fi

echo "\nProvider pointer (state/${PROVIDER}/${PROFILE}/last_success.json):"
if ! aws s3 cp "s3://${BUCKET}/${PREFIX}/state/${PROVIDER}/${PROFILE}/last_success.json" - 2>/dev/null; then
  echo "(missing)"
fi

echo "\nLatest run_id:" 
latest_run_id=$(aws s3api list-objects-v2 \
  --bucket "${BUCKET}" \
  --prefix "${PREFIX}/runs/" \
  --query "Contents[].Key" \
  --output json | \
  jq -r '.[]? | capture("/runs/(?<rid>[^/]+)/") | .rid' | sort | tail -n 1)

if [[ -z "${latest_run_id}" ]]; then
  echo "(none)"
  exit 0
fi

echo "${latest_run_id}"

echo "\nLatest run_report.json (diff_counts + baseline):"
aws s3 cp "s3://${BUCKET}/${PREFIX}/runs/${latest_run_id}/run_report.json" - 2>/dev/null | \
  jq -r '
    "success: \(.success)",
    "baseline_run_id: \(.delta_summary.baseline_run_id)",
    "diff_counts: \(.diff_counts)"
  '
