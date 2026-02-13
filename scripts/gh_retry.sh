#!/usr/bin/env bash
set -euo pipefail

if [[ $# -eq 0 ]]; then
  echo "usage: scripts/gh_retry.sh <gh args...>" >&2
  echo "example: scripts/gh_retry.sh pr checks 123 --watch" >&2
  exit 2
fi

if ! command -v gh >/dev/null 2>&1; then
  echo "gh_retry: GitHub CLI ('gh') is not installed" >&2
  exit 127
fi

max_attempts="${GH_RETRY_MAX_ATTEMPTS:-4}"
sleep_seconds="${GH_RETRY_SLEEP_SECONDS:-2}"

if ! [[ "$max_attempts" =~ ^[0-9]+$ ]] || [[ "$max_attempts" -lt 1 ]]; then
  echo "gh_retry: GH_RETRY_MAX_ATTEMPTS must be a positive integer" >&2
  exit 2
fi
if ! [[ "$sleep_seconds" =~ ^[0-9]+$ ]] || [[ "$sleep_seconds" -lt 0 ]]; then
  echo "gh_retry: GH_RETRY_SLEEP_SECONDS must be a non-negative integer" >&2
  exit 2
fi

attempt=1
while [[ "$attempt" -le "$max_attempts" ]]; do
  tmp_err="$(mktemp)"
  if gh "$@" 2> >(tee "$tmp_err" >&2); then
    rm -f "$tmp_err"
    exit 0
  fi
  exit_code=$?
  err_text="$(cat "$tmp_err" || true)"
  rm -f "$tmp_err"

  if [[ "$attempt" -ge "$max_attempts" ]]; then
    echo "gh_retry: giving up after ${attempt}/${max_attempts} attempts (exit=${exit_code})" >&2
    exit "$exit_code"
  fi

  if grep -Eqi "error connecting to api\.github\.com|could not resolve host|temporary failure in name resolution|lookup api\.github\.com|dial tcp|i/o timeout|context deadline exceeded|tls handshake timeout" <<<"$err_text"; then
    echo "gh_retry: transient network/DNS error on attempt ${attempt}/${max_attempts}; retrying in ${sleep_seconds}s..." >&2
    sleep "$sleep_seconds"
    attempt=$((attempt + 1))
    continue
  fi

  # Non-network error (permission, bad args, failing checks, etc.) should fail fast.
  exit "$exit_code"
done
