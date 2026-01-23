#!/usr/bin/env bash
set -euo pipefail

# Usage (env only):
#   LOG_GROUP=/ecs/jobintel REGION=us-east-1 LOOKBACK_MINUTES=60 FILTER=baseline ./scripts/cw_tail.sh
#
# Safe filters (avoid slashes): baseline | last_success | publish | availability | ProviderFetchError

LOG_GROUP="${LOG_GROUP:-/ecs/jobintel}"
REGION="${REGION:-${AWS_REGION:-us-east-1}}"
LOOKBACK_MINUTES="${LOOKBACK_MINUTES:-60}"
FILTER="${FILTER:-}"
ORDER="${ORDER:-newest}"

if [[ $# -ne 0 ]]; then
  echo "This script uses env vars only; no positional args are accepted." >&2
  echo "Example: LOG_GROUP=/ecs/jobintel REGION=us-east-1 LOOKBACK_MINUTES=60 FILTER=baseline ./scripts/cw_tail.sh" >&2
  exit 2
fi

STATUS=0
fail() {
  local msg="$1"
  echo "FAIL: ${msg}" >&2
  STATUS=1
}

command -v aws >/dev/null 2>&1 || fail "aws CLI is required."
if [[ -z "${LOG_GROUP}" ]]; then
  fail "LOG_GROUP is required."
fi

if [[ "${STATUS}" -ne 0 ]]; then
  echo "Example: LOG_GROUP=/ecs/jobintel REGION=us-east-1 LOOKBACK_MINUTES=60 FILTER=baseline ./scripts/cw_tail.sh" >&2
  exit 2
fi

start_time=$((($(date +%s)-LOOKBACK_MINUTES*60)*1000))

args=(--log-group-name "${LOG_GROUP}" --start-time "${start_time}" --region "${REGION}")
if [[ -n "${FILTER}" ]]; then
  args+=(--filter-pattern "${FILTER}")
fi

if [[ "${ORDER}" == "newest" ]]; then
  aws logs filter-log-events "${args[@]}" --query 'events | reverse(@)' --output text || fail "CloudWatch query failed."
else
  aws logs filter-log-events "${args[@]}" --query 'events' --output text || fail "CloudWatch query failed."
fi

echo "\nSummary:"
if [[ "${STATUS}" -eq 0 ]]; then
  echo "SUCCESS: logs fetched."
else
  echo "FAIL: see messages above."
fi
exit "${STATUS}"
