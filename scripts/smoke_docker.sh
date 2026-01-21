#!/usr/bin/env bash
set -euo pipefail

CONTAINER_NAME=${CONTAINER_NAME:-jobintel_smoke}
ARTIFACT_DIR=${ARTIFACT_DIR:-smoke_artifacts}
IMAGE_TAG=${IMAGE_TAG:-jobintel:local}
SMOKE_SKIP_BUILD=${SMOKE_SKIP_BUILD:-0}

if [ "${1:-}" = "--skip-build" ]; then
  SMOKE_SKIP_BUILD=1
  shift
fi

if [ "$#" -ne 0 ]; then
  echo "Usage: $0 [--skip-build]"
  exit 2
fi

mkdir -p "$ARTIFACT_DIR"

cleanup() {
  docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
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

docker create --name "$CONTAINER_NAME" \
  "$IMAGE_TAG" --providers openai --profiles cs --offline --no_post --no_enrich >/dev/null

set +e
docker start -a "$CONTAINER_NAME" 2>&1 | tee "$ARTIFACT_DIR/container.log"
status=${PIPESTATUS[0]}
set -e

echo "$status" > "$ARTIFACT_DIR/exit_code.txt"
if [ "$status" -ne 0 ]; then
  echo "Container failed; last 80 lines of logs:"
  tail -n 80 "$ARTIFACT_DIR/container.log" || true
fi

echo "==> Collect outputs"
missing=0
for path in /app/data/openai_labeled_jobs.json /app/data/openai_ranked_jobs.cs.json /app/data/openai_ranked_jobs.cs.csv; do
  if ! docker cp "$CONTAINER_NAME:$path" "$ARTIFACT_DIR/$(basename "$path")" 2>/dev/null; then
    echo "Missing output: $path"
    missing=1
  fi
done

rm -rf "$ARTIFACT_DIR/state_runs"
if docker cp "$CONTAINER_NAME:/app/state/runs" "$ARTIFACT_DIR/state_runs" 2>/dev/null; then
  run_report="$(ls -1 "$ARTIFACT_DIR"/state_runs/*.json 2>/dev/null | sort | tail -n 1)"
  if [ -n "$run_report" ]; then
    cp "$run_report" "$ARTIFACT_DIR/run_report.json" 2>/dev/null || true
  fi
fi

if [ "$missing" -ne 0 ]; then
  echo "Available /app/data contents:"
  docker cp "$CONTAINER_NAME:/app/data" "$ARTIFACT_DIR/data" 2>/dev/null || true
  ls -la "$ARTIFACT_DIR/data" 2>/dev/null || true
fi

PYTHON=${PYTHON:-python3}
echo "==> Smoke contract check"
$PYTHON scripts/smoke_contract_check.py "$ARTIFACT_DIR"

if [ "$status" -ne 0 ] || [ "$missing" -ne 0 ]; then
  echo "Smoke failed (exit_code=$status, missing_outputs=$missing)"
  exit 1
fi

echo "Smoke succeeded. Artifacts in $ARTIFACT_DIR"
