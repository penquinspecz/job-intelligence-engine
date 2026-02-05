#!/usr/bin/env bash
set -euo pipefail

NS="${NS:-jobintel}"
TIMEOUT="${TIMEOUT:-15m}"
TS="$(date +%Y%m%d%H%M%S)"
JOB_NAME="jobintel-liveproof-${TS}"
echo "Creating job ${JOB_NAME} from cronjob jobintel-daily in namespace ${NS}..."
kubectl -n "${NS}" create job --from=cronjob/jobintel-daily "${JOB_NAME}"

echo "Setting LIVE args and required env..."
kubectl -n "${NS}" set env "job/${JOB_NAME}" CAREERS_MODE=LIVE PUBLISH_S3_REQUIRE=1
kubectl -n "${NS}" set args "job/${JOB_NAME}" -- \
  python scripts/run_daily.py \
  --profiles cs \
  --us_only \
  --no_post

echo "Waiting for job completion (timeout=${TIMEOUT})..."
kubectl -n "${NS}" wait --for=condition=complete "job/${JOB_NAME}" --timeout="${TIMEOUT}"

POD_NAME="$(kubectl -n "${NS}" get pods -l "job-name=${JOB_NAME}" -o jsonpath='{.items[0].metadata.name}')"
NODE_NAME="$(kubectl -n "${NS}" get pod "${POD_NAME}" -o jsonpath='{.spec.nodeName}')"
NODEGROUP="$(kubectl get node "${NODE_NAME}" -o jsonpath='{.metadata.labels.eks\.amazonaws\.com/nodegroup}' 2>/dev/null || true)"

LOGS="$(kubectl -n "${NS}" logs "job/${JOB_NAME}")"
RUN_ID="$(echo "${LOGS}" | sed -n 's/.*JOBINTEL_RUN_ID=//p' | head -n 1)"
PROV_LINE="$(echo "${LOGS}" | grep -F '[run_scrape][provenance]' | tail -n 1 || true)"

echo "pod_name=${POD_NAME}"
echo "node_name=${NODE_NAME}"
echo "nodegroup=${NODEGROUP}"
echo "JOBINTEL_RUN_ID=${RUN_ID}"
echo "provenance=${PROV_LINE}"

if [[ -z "${PROV_LINE}" ]]; then
  echo "missing provenance line" >&2
  exit 3
fi

PROV_JSON="$(echo "${PROV_LINE}" | sed 's/^.*\\[run_scrape\\]\\[provenance\\] //')"
extract_field() {
  local key="$1"
  echo "${PROV_JSON}" | sed -n "s/.*\\\"${key}\\\": \\([^,}]*\\).*/\\1/p" | head -n 1 | tr -d '\"'
}

PROV_MODE="$(extract_field mode)"
PROV_SCRAPE_MODE="$(extract_field scrape_mode)"
PROV_LIVE_ATTEMPTED="$(extract_field live_attempted)"
PROV_LIVE_RESULT="$(extract_field live_result)"
PROV_LIVE_HTTP_STATUS="$(extract_field live_http_status)"
PROV_LIVE_ERROR_TYPE="$(extract_field live_error_type)"

[[ -n "${PROV_MODE}" ]] && echo "mode=${PROV_MODE}"
[[ -n "${PROV_SCRAPE_MODE}" ]] && echo "scrape_mode=${PROV_SCRAPE_MODE}"
[[ -n "${PROV_LIVE_ATTEMPTED}" ]] && echo "live_attempted=${PROV_LIVE_ATTEMPTED}"
[[ -n "${PROV_LIVE_RESULT}" ]] && echo "live_result=${PROV_LIVE_RESULT}"
[[ -n "${PROV_LIVE_HTTP_STATUS}" ]] && echo "live_http_status=${PROV_LIVE_HTTP_STATUS}"
[[ -n "${PROV_LIVE_ERROR_TYPE}" ]] && echo "live_error_type=${PROV_LIVE_ERROR_TYPE}"

if echo "${PROV_LINE}" | grep -q '"live_attempted": false'; then
  echo "live_attempted=false in provenance" >&2
  exit 3
fi

if echo "${PROV_LINE}" | grep -q '"live_result": "skipped"'; then
  echo "live_result=skipped in provenance" >&2
  exit 3
fi

echo "live proof: ok"
