#!/usr/bin/env bash
set -euo pipefail

CONTAINER_NAME=${CONTAINER_NAME:-jobintel_smoke}
ARTIFACT_DIR=${ARTIFACT_DIR:-smoke_artifacts}
IMAGE_TAG=${IMAGE_TAG:-${JOBINTEL_IMAGE_TAG:-jobintel:local}}
SMOKE_SKIP_BUILD=${SMOKE_SKIP_BUILD:-0}
SMOKE_PROVIDERS=${SMOKE_PROVIDERS:-openai}
SMOKE_PROFILES=${SMOKE_PROFILES:-cs}
PROVIDERS=${PROVIDERS:-$SMOKE_PROVIDERS}
PROFILES=${PROFILES:-$SMOKE_PROFILES}
SMOKE_TAIL_LINES=${SMOKE_TAIL_LINES:-0}
container_created=0
status=1

if [ "${DOCKER_BUILDKIT:-1}" = "0" ]; then
  echo "BuildKit is required (Dockerfile uses RUN --mount=type=cache). Set DOCKER_BUILDKIT=1."
  exit 1
fi

write_exit_code() {
  mkdir -p "$ARTIFACT_DIR"
  echo "$status" > "$ARTIFACT_DIR/exit_code.txt"
}

write_docker_context() {
  mkdir -p "$ARTIFACT_DIR"
  {
    echo "context: $(docker context show 2>/dev/null || echo unknown)"
    echo "host: $(docker context inspect "$(docker context show 2>/dev/null || echo default)" --format '{{json .Endpoints.docker.Host}}' 2>/dev/null || echo unknown)"
    echo "docker version:"
    docker version 2>/dev/null || true
    echo "docker info:"
    docker info 2>/dev/null || true
  } > "$ARTIFACT_DIR/docker_context.txt"
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

echo "==> Image tag: $IMAGE_TAG"
context="$(docker context show 2>/dev/null || echo unknown)"
host="$(docker context inspect "$context" --format '{{json .Endpoints.docker.Host}}' 2>/dev/null || echo unknown)"
echo "==> Config: image=$IMAGE_TAG providers=$PROVIDERS profiles=$PROFILES skip_build=$SMOKE_SKIP_BUILD context=$context host=$host"
write_docker_context

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

echo "==> Preflight image runtime"
preflight_status=1
last_cmd=""
last_output=""
for cmd in "/usr/local/bin/python -V" "/usr/bin/python3 -V" "python3 -V" "python -V"; do
  set +e
  entrypoint="${cmd%% *}"
  args="${cmd#* }"
  last_output="$(docker run --rm --entrypoint "$entrypoint" "$IMAGE_TAG" $args 2>&1)"
  preflight_status=$?
  set -e
  last_cmd="docker run --rm --entrypoint $entrypoint $IMAGE_TAG $args"
  if [ "$preflight_status" -eq 0 ]; then
    break
  fi
done
if [ "$preflight_status" -ne 0 ]; then
  echo "Preflight failed: unable to run python in image '$IMAGE_TAG'."
  echo "Last command: $last_cmd"
  echo "Last error output:"
  echo "$last_output"
  echo "Preflight bypasses the image ENTRYPOINT; failures mean python is missing or"
  echo "the $IMAGE_TAG tag may have been overwritten by a non-jobintel image."
  echo "Rebuild with: make image"
  exit 1
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
  docker start -a "$CONTAINER_NAME" 2>&1 | tee "$ARTIFACT_DIR/smoke.log"
  status=${PIPESTATUS[0]}
  set -e
else
  echo "Failed to create smoke container (exit_code=$create_status)"
  status=$create_status
fi

if [ "$status" -ne 0 ] && [ "${SMOKE_TAIL_LINES:-0}" -gt 0 ]; then
  echo "Container failed; last ${SMOKE_TAIL_LINES} lines of logs:"
  tail -n "$SMOKE_TAIL_LINES" "$ARTIFACT_DIR/smoke.log" || true
fi

echo "==> Collect outputs"
missing=0
IFS=',' read -r -a provider_list <<< "$PROVIDERS"
IFS=',' read -r -a profile_list <<< "$PROFILES"

copy_from_container() {
  local src="$1"
  local required="$2"
  if [ "$container_created" -ne 1 ]; then
    echo "Skipping copy (container not created): $src"
    if [ "$required" = "1" ]; then
      missing=1
    fi
    return
  fi
  if ! docker cp "$CONTAINER_NAME:$src" "$ARTIFACT_DIR/$(basename "$src")" 2>/dev/null; then
    if [ "$required" = "1" ]; then
      echo "Missing output: $src"
      missing=1
    else
      echo "Missing optional output: $src"
    fi
  fi
}

for provider in "${provider_list[@]}"; do
  provider_trimmed="$(echo "$provider" | xargs)"
  if [ -z "$provider_trimmed" ]; then
    continue
  fi
  copy_from_container "/app/data/${provider_trimmed}_labeled_jobs.json" 1
  for profile in "${profile_list[@]}"; do
    profile_trimmed="$(echo "$profile" | xargs)"
    if [ -z "$profile_trimmed" ]; then
      continue
    fi
    copy_from_container "/app/data/${provider_trimmed}_ranked_jobs.${profile_trimmed}.json" 1
    copy_from_container "/app/data/${provider_trimmed}_ranked_jobs.${profile_trimmed}.csv" 1
    copy_from_container "/app/data/${provider_trimmed}_shortlist.${profile_trimmed}.md" 0
    copy_from_container "/app/data/${provider_trimmed}_ranked_families.${profile_trimmed}.json" 0
  done
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
echo "==> Write metadata"
$PYTHON -m scripts.smoke_metadata --out "$ARTIFACT_DIR/metadata.json" --providers "$PROVIDERS" --profiles "$PROFILES"

echo "==> Smoke contract check"
$PYTHON scripts/smoke_contract_check.py "$ARTIFACT_DIR" --providers "$PROVIDERS" --profiles "$PROFILES"

if [ "$status" -ne 0 ] || [ "$missing" -ne 0 ]; then
  echo "Smoke failed (exit_code=$status, missing_outputs=$missing)"
  exit 1
fi

echo "Smoke succeeded. Artifacts in $ARTIFACT_DIR"
