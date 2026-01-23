#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 0 ]]; then
  echo "This script uses env vars only; no positional args are accepted." >&2
  echo "Example: CLUSTER_ARN=... TASK_FAMILY=jobintel-daily REGION=us-east-1 SUBNET_IDS=subnet-1,subnet-2 SECURITY_GROUP_IDS=sg-1 BUCKET=... PREFIX=jobintel ./scripts/run_ecs_once.sh" >&2
  exit 2
fi

CLUSTER_ARN="${CLUSTER_ARN:-}"
TASK_FAMILY="${TASK_FAMILY:-}"
TASKDEF_ARN="${TASKDEF_ARN:-}"
TASKDEF_REV="${TASKDEF_REV:-}"
REQUIRE_LATEST_TASKDEF="${REQUIRE_LATEST_TASKDEF:-1}"
REGION="${REGION:-${AWS_REGION:-us-east-1}}"
SUBNET_IDS="${SUBNET_IDS:-}"
SECURITY_GROUP_IDS="${SECURITY_GROUP_IDS:-}"
BUCKET="${BUCKET:-${JOBINTEL_S3_BUCKET:-}}"
PREFIX="${PREFIX:-${JOBINTEL_S3_PREFIX:-jobintel}}"
PROVIDER="${PROVIDER:-openai}"
PROFILE="${PROFILE:-cs}"
TAIL_LOGS="${TAIL_LOGS:-0}"
LOOKBACK_MINUTES="${LOOKBACK_MINUTES:-60}"
PRINT_RUN_REPORT="${PRINT_RUN_REPORT:-0}"

STATUS=0
fail() {
  local msg="$1"
  echo "FAIL: ${msg}" >&2
  STATUS=1
}

command -v aws >/dev/null 2>&1 || fail "aws CLI is required."
PYTHON_BIN="${PYTHON_BIN:-}"
if [[ -z "${PYTHON_BIN}" ]]; then
  PYTHON_BIN="$(command -v python3 || command -v python || true)"
fi
if [[ -z "${PYTHON_BIN}" ]]; then
  fail "python3 (or python) is required."
fi

if [[ -z "${CLUSTER_ARN}" || -z "${TASK_FAMILY}" ]]; then
  fail "CLUSTER_ARN and TASK_FAMILY are required."
fi
if [[ -z "${SUBNET_IDS}" || -z "${SECURITY_GROUP_IDS}" ]]; then
  fail "SUBNET_IDS and SECURITY_GROUP_IDS are required for awsvpc."
fi
if [[ -z "${BUCKET}" ]]; then
  fail "BUCKET is required (or set JOBINTEL_S3_BUCKET)."
fi

if [[ "${STATUS}" -ne 0 ]]; then
  echo "Example: CLUSTER_ARN=... TASK_FAMILY=jobintel-daily REGION=us-east-1 SUBNET_IDS=subnet-1,subnet-2 SECURITY_GROUP_IDS=sg-1 BUCKET=... PREFIX=jobintel ./scripts/run_ecs_once.sh" >&2
  exit 2
fi

subnets_json=$("${PYTHON_BIN}" - <<PY
import json
print(json.dumps([s.strip() for s in "${SUBNET_IDS}".split(",") if s.strip()]))
PY
)

sg_json=$("${PYTHON_BIN}" - <<PY
import json
print(json.dumps([s.strip() for s in "${SECURITY_GROUP_IDS}".split(",") if s.strip()]))
PY
)

if [[ -n "${TASKDEF_ARN}" && -n "${TASKDEF_REV}" ]]; then
  fail "Set only one of TASKDEF_ARN or TASKDEF_REV."
fi

if [[ -n "${TASKDEF_ARN}" ]]; then
  TASK_DEF_ARN="${TASKDEF_ARN}"
elif [[ -n "${TASKDEF_REV}" ]]; then
  TASK_DEF_ARN="${TASK_FAMILY}:${TASKDEF_REV}"
else
  if [[ "${REQUIRE_LATEST_TASKDEF}" == "1" ]]; then
    TASK_DEF_ARN=$(aws ecs list-task-definitions \
      --family-prefix "${TASK_FAMILY}" \
      --sort DESC \
      --max-items 1 \
      --region "${REGION}" \
      --query 'taskDefinitionArns[0]' \
      --output text)
  else
    TASK_DEF_ARN="${TASK_FAMILY}"
  fi
fi

if [[ -z "${TASK_DEF_ARN}" || "${TASK_DEF_ARN}" == "None" ]]; then
  fail "No task definition found for family ${TASK_FAMILY}."
  echo "Summary:\nFAIL"; exit 1
fi

taskdef_desc=$(aws ecs describe-task-definition --task-definition "${TASK_DEF_ARN}" --region "${REGION}")
taskdef_image=$("${PYTHON_BIN}" - <<PY
import json
payload=json.loads('''${taskdef_desc}''')
containers = payload.get("taskDefinition", {}).get("containerDefinitions", [])
print(containers[0].get("image") if containers else "")
PY
)

echo "Task definition: ${TASK_DEF_ARN}"
echo "Task image: ${taskdef_image:-unknown}"

# Run task
run_out=$(aws ecs run-task \
  --cluster "${CLUSTER_ARN}" \
  --launch-type FARGATE \
  --task-definition "${TASK_DEF_ARN}" \
  --network-configuration "awsvpcConfiguration={subnets=${subnets_json},securityGroups=${sg_json},assignPublicIp=ENABLED}" \
  --region "${REGION}")

task_arn=$("${PYTHON_BIN}" - <<PY
import json
payload=json.loads('''${run_out}''')
print(payload.get('tasks', [{}])[0].get('taskArn', ''))
PY
)

if [[ -z "${task_arn}" ]]; then
  fail "Task failed to start (no taskArn)."
  echo "Summary:\nFAIL"; exit 1
fi

echo "Task ARN: ${task_arn}"

echo "Waiting for task to stop..."
aws ecs wait tasks-stopped --cluster "${CLUSTER_ARN}" --tasks "${task_arn}" --region "${REGION}" || true

desc=$(aws ecs describe-tasks --cluster "${CLUSTER_ARN}" --tasks "${task_arn}" --region "${REGION}")

exit_code=$("${PYTHON_BIN}" - <<PY
import json
payload=json.loads('''${desc}''')
containers = payload.get('tasks', [{}])[0].get('containers', [])
print(containers[0].get('exitCode') if containers else None)
PY
)

stopped_reason=$("${PYTHON_BIN}" - <<PY
import json
payload=json.loads('''${desc}''')
print(payload.get('tasks', [{}])[0].get('stoppedReason'))
PY
)

# Fetch latest run_report and last_success pointers
last_success_global=$(aws s3 cp "s3://${BUCKET}/${PREFIX}/state/last_success.json" - 2>/dev/null || true)
last_success_provider=$(aws s3 cp "s3://${BUCKET}/${PREFIX}/state/${PROVIDER}/${PROFILE}/last_success.json" - 2>/dev/null || true)

pointer_written="no"
if [[ -n "${last_success_provider}" || -n "${last_success_global}" ]]; then
  pointer_written="yes"
fi

latest_run_id=$(aws s3api list-objects-v2 \
  --bucket "${BUCKET}" \
  --prefix "${PREFIX}/runs/" \
  --region "${REGION}" \
  --query "Contents[].Key" \
  --output json | \
  "${PYTHON_BIN}" - <<'PY'
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

run_report_uri="s3://${BUCKET}/${PREFIX}/runs/${latest_run_id}/run_report.json"
run_report=$(aws s3 cp "${run_report_uri}" - 2>/dev/null || true)

baseline_resolved="no"
new_count="?"
changed_count="?"
removed_count="?"

if [[ -n "${run_report}" ]]; then
  "${PYTHON_BIN}" - <<PY
import json
import os

data=json.loads('''${run_report}''')
provider=os.environ.get("PROVIDER","openai")
profile=os.environ.get("PROFILE","cs")
baseline = data.get("delta_summary", {})
resolved = False
for prov, profiles in (baseline.get("provider_profile", {}) or {}).items():
    if prov != provider:
        continue
    for prof, entry in (profiles or {}).items():
        if prof == profile:
            resolved = bool(entry.get("baseline_resolved"))
            print("baseline_resolved:", "yes" if resolved else "no")
            print("diff_counts:", entry.get("new_job_count"), entry.get("changed_job_count"), entry.get("removed_job_count"))
PY
fi

if [[ -n "${run_report}" ]]; then
  baseline_resolved=$("${PYTHON_BIN}" - <<PY
import json, os

data=json.loads('''${run_report}''')
provider=os.environ.get("PROVIDER","openai")
profile=os.environ.get("PROFILE","cs")
entry = data.get("delta_summary", {}).get("provider_profile", {}).get(provider, {}).get(profile, {})
print("yes" if entry.get("baseline_resolved") else "no")
PY
)
  new_count=$("${PYTHON_BIN}" - <<PY
import json, os

data=json.loads('''${run_report}''')
provider=os.environ.get("PROVIDER","openai")
profile=os.environ.get("PROFILE","cs")
entry = data.get("delta_summary", {}).get("provider_profile", {}).get(provider, {}).get(profile, {})
print(entry.get("new_job_count", "?"))
PY
)
  changed_count=$("${PYTHON_BIN}" - <<PY
import json, os

data=json.loads('''${run_report}''')
provider=os.environ.get("PROVIDER","openai")
profile=os.environ.get("PROFILE","cs")
entry = data.get("delta_summary", {}).get("provider_profile", {}).get(provider, {}).get(profile, {})
print(entry.get("changed_job_count", "?"))
PY
)
  removed_count=$("${PYTHON_BIN}" - <<PY
import json, os

data=json.loads('''${run_report}''')
provider=os.environ.get("PROVIDER","openai")
profile=os.environ.get("PROFILE","cs")
entry = data.get("delta_summary", {}).get("provider_profile", {}).get(provider, {}).get(profile, {})
print(entry.get("removed_job_count", "?"))
PY
)
fi

if [[ "${exit_code}" != "0" && "${exit_code}" != "None" ]]; then
  fail "Task exit_code=${exit_code}"
fi

if [[ "${pointer_written}" != "yes" ]]; then
  fail "Baseline pointer missing (state/last_success.json)."
fi

if [[ "${baseline_resolved}" != "yes" ]]; then
  fail "Baseline not resolved for ${PROVIDER}/${PROFILE}."
fi

if [[ "${PRINT_RUN_REPORT}" == "1" ]]; then
  pointer_json="${last_success_provider:-${last_success_global}}"
  pointer_run_path=$("${PYTHON_BIN}" - <<PY
import json
import sys

payload = '''${pointer_json}'''
try:
    data = json.loads(payload)
except Exception:
    data = {}
run_path = (data or {}).get("run_path", "") or ""
if run_path.startswith("/"):
    run_path = run_path[1:]
print(run_path, end="")
PY
)
  if [[ -n "${pointer_run_path}" ]]; then
    run_report_uri="s3://${BUCKET}/${pointer_run_path%/}/run_report.json"
  fi
  echo "\nrun_report_uri: ${run_report_uri}"
fi

if [[ "${TAIL_LOGS}" == "1" ]]; then
  if [[ -x "./scripts/cw_tail.sh" ]]; then
    FILTER=baseline LOOKBACK_MINUTES="${LOOKBACK_MINUTES}" REGION="${REGION}" ./scripts/cw_tail.sh || true
  else
    echo "WARN: scripts/cw_tail.sh not found or not executable."
  fi
fi

echo "\nVerdict:"
echo "exit_code: ${exit_code:-unknown}"
echo "stopped_reason: ${stopped_reason:-unknown}"
echo "baseline_resolved: ${baseline_resolved}"
echo "new/changed/removed: ${new_count}/${changed_count}/${removed_count}"
echo "pointer_written: ${pointer_written}"

echo "\nSummary:"
if [[ "${STATUS}" -eq 0 ]]; then
  echo "SUCCESS"
else
  echo "FAIL"
fi
exit "${STATUS}"
