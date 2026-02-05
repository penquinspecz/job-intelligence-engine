#!/usr/bin/env bash
set -euo pipefail

NS="${NS:-jobintel}"
JOB_NAME="${1:-}"

usage() {
  echo "usage: NS=<namespace> $0 <job-name>" >&2
  echo "example: NS=jobintel $0 jobintel-liveproof-20260205" >&2
}

if [[ -z "${JOB_NAME}" ]]; then
  usage
  exit 2
fi

LOGS="$(kubectl -n "${NS}" logs "job/${JOB_NAME}")"
RUN_ID="$(echo "${LOGS}" | sed -n 's/.*JOBINTEL_RUN_ID=//p' | head -n 1)"
PROV_LINE="$(echo "${LOGS}" | grep -F '[run_scrape][provenance]' | tail -n 1 || true)"

if [[ -z "${RUN_ID}" ]]; then
  echo "missing JOBINTEL_RUN_ID in logs" >&2
  exit 3
fi
if [[ -z "${PROV_LINE}" ]]; then
  echo "missing provenance line in logs" >&2
  exit 3
fi

if ! echo "${PROV_LINE}" | grep -q '"live_attempted": true'; then
  echo "live_attempted!=true in provenance" >&2
  exit 3
fi
if ! echo "${PROV_LINE}" | grep -q '"live_result": "success"'; then
  echo "live_result!=success in provenance" >&2
  exit 3
fi

if echo "${LOGS}" | grep -q "s3_status=ok"; then
  : # ok
elif echo "${LOGS}" | grep -q "PUBLISH_CONTRACT enabled=True" && echo "${LOGS}" | grep -q "pointer_global=ok"; then
  : # ok
else
  echo "missing publish success markers (s3_status=ok or publish contract ok)" >&2
  exit 3
fi

echo "job_name=${JOB_NAME}"
echo "namespace=${NS}"
echo "JOBINTEL_RUN_ID=${RUN_ID}"
echo "ok"
