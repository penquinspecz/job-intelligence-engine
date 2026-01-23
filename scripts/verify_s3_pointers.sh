#!/usr/bin/env bash
set -euo pipefail

BUCKET="${BUCKET:-${JOBINTEL_S3_BUCKET:-}}"
PREFIX="${PREFIX:-${JOBINTEL_S3_PREFIX:-jobintel}}"
PROVIDER="${PROVIDER:-openai}"
PROFILE="${PROFILE:-cs}"

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
  python - <<'PY'
import json
import sys
from datetime import datetime

def parse_run_id(key: str) -> str | None:
    marker = "/runs/"
    if marker not in key:
        return None
    rest = key.split(marker, 1)[1]
    run_id = rest.split("/", 1)[0]
    return run_id or None

keys = json.load(sys.stdin) if not sys.stdin.closed else []
run_ids = {parse_run_id(k) for k in keys}
run_ids.discard(None)

candidates = []
for run_id in run_ids:
    try:
        dt = datetime.fromisoformat(run_id.replace("Z", "+00:00"))
        candidates.append((dt, run_id))
    except Exception:
        candidates.append((run_id, run_id))

if not candidates:
    print("", end="")
else:
    candidates.sort()
    print(candidates[-1][1], end="")
PY
)

if [[ -z "${latest_run_id}" ]]; then
  echo "(none)"
  exit 0
fi

echo "${latest_run_id}"

echo "\nLatest run_report.json (diff_counts + baseline):"
aws s3 cp "s3://${BUCKET}/${PREFIX}/runs/${latest_run_id}/run_report.json" - 2>/dev/null | \
  python - <<'PY'
import json
import sys

data = json.load(sys.stdin)
print("success:", data.get("success"))
print("baseline_run_id:", data.get("delta_summary", {}).get("baseline_run_id"))
print("diff_counts:", data.get("diff_counts"))
PY
