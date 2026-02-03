#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/.." && pwd)"
cd "$repo_root"

changed="$(git diff --name-only -- data/*_snapshots 2>/dev/null || true)"
if [ -n "$changed" ]; then
  echo "ERROR: Snapshot fixtures were modified during tests."
  echo "Do not mutate committed fixtures under data/*_snapshots."
  echo "To update snapshots, use the explicit snapshot-update workflow."
  echo ""
  echo "Changed files:"
  echo "$changed"
  exit 1
fi
