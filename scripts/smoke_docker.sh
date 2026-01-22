#!/usr/bin/env bash
set -euo pipefail

CONTAINER_NAME=${CONTAINER_NAME:-jobintel_smoke}
ARTIFACT_DIR=${ARTIFACT_DIR:-smoke_artifacts}
IMAGE_TAG=${IMAGE_TAG:-jobintel:local}
SMOKE_SKIP_BUILD=${SMOKE_SKIP_BUILD:-0}
PROVIDERS=${PROVIDERS:-openai}
PROFILES=${PROFILES:-cs}
SMOKE_TAIL_LINES=${SMOKE_TAIL_LINES:-0}
container_created=0
status=1

write_exit_code() {
  mkdir -p "$ARTIFACT_DIR"
  echo "$status" > "$ARTIFACT_DIR/exit_code.txt"
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --skip-build)
      SMOKE_SKIP_BUILD=1
      shift
      ;;
    --tail)
      SMOKE_TAIL_LINES="${2:-0}"
      shift 2
      ;;
    --providers)
      PROVIDERS="${2:-}"
      shift 2
      ;;
    --profiles)
      PROFILES="${2:-}"
      shift 2
      ;;
    *)
      echo "Usage: $0 [--skip-build] [--tail <lines>] [--providers <ids>] [--profiles <profiles>]"
      exit 2
      ;;
  esac
done

mkdir -p "$ARTIFACT_DIR"

cleanup() {
  docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
  write_exit_code
}
trap cleanup EXIT

if [ "$SMOKE_SKIP_BUILD" = "1" ]; then
  if ! docker image inspect "$IMAGE_TAG" >/dev/null 2>&1; then
    echo "Missing image '$IMAGE_TAG'. Build it first (docker build -t $IMAGE_TAG .) or omit --skip-build."
    exit 1
  fi
  echo "==> Using existing image ($IMAGE_TAG)"
else
  echo "==> Build image ($IMAGE_TAG)"
  docker build -t "$IMAGE_TAG" .
fi

echo "==> Validate baked-in snapshots"
docker run --rm --entrypoint python "$IMAGE_TAG" \
  -m src.jobintel.cli snapshots validate --all --data-dir /app/data

echo "==> Run smoke container ($CONTAINER_NAME)"
docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true

set +e
docker create --name "$CONTAINER_NAME" \
  "$IMAGE_TAG" --providers "$PROVIDERS" --profiles "$PROFILES" --offline --no_post --no_enrich >/dev/null
create_status=$?
set -e
if [ "$create_status" -eq 0 ]; then
  container_created=1
  set +e
  docker start -a "$CONTAINER_NAME" 2>&1 | tee "$ARTIFACT_DIR/container.log"
  status=${PIPESTATUS[0]}
  set -e
else
  echo "Failed to create smoke container (exit_code=$create_status)"
  status=$create_status
fi

if [ "$status" -ne 0 ] && [ "${SMOKE_TAIL_LINES:-0}" -gt 0 ]; then
  echo "Container failed; last ${SMOKE_TAIL_LINES} lines of logs:"
  tail -n "$SMOKE_TAIL_LINES" "$ARTIFACT_DIR/container.log" || true
fi

echo "==> Collect outputs"
missing=0
for path in /app/data/openai_labeled_jobs.json /app/data/openai_ranked_jobs.cs.json /app/data/openai_ranked_jobs.cs.csv; do
  if [ "$container_created" -ne 1 ]; then
    echo "Skipping copy (container not created): $path"
    missing=1
    continue
  fi
  if ! docker cp "$CONTAINER_NAME:$path" "$ARTIFACT_DIR/$(basename "$path")" 2>/dev/null; then
    echo "Missing output: $path"
    missing=1
  fi
done

rm -rf "$ARTIFACT_DIR/state_runs"
if [ "$container_created" -eq 1 ] && docker cp "$CONTAINER_NAME:/app/state/runs" "$ARTIFACT_DIR/state_runs" 2>/dev/null; then
  run_report="$(ls -1 "$ARTIFACT_DIR"/state_runs/*.json 2>/dev/null | sort | tail -n 1)"
  if [ -n "$run_report" ]; then
    cp "$run_report" "$ARTIFACT_DIR/run_report.json" 2>/dev/null || true
  fi
fi

if [ "$missing" -ne 0 ]; then
  echo "Available /app/data contents:"
  if [ "$container_created" -eq 1 ]; then
    docker cp "$CONTAINER_NAME:/app/data" "$ARTIFACT_DIR/data" 2>/dev/null || true
    ls -la "$ARTIFACT_DIR/data" 2>/dev/null || true
  fi
fi

PYTHON=${PYTHON:-python3}
echo "==> Smoke contract check"
$PYTHON scripts/smoke_contract_check.py "$ARTIFACT_DIR" --providers "$PROVIDERS" --profiles "$PROFILES"

if [ "$status" -ne 0 ] || [ "$missing" -ne 0 ]; then
  echo "Smoke failed (exit_code=$status, missing_outputs=$missing)"
  exit 1
fi

echo "Smoke succeeded. Artifacts in $ARTIFACT_DIR"
