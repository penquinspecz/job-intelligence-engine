#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VENV_PY="${REPO_DIR}/.venv/bin/python"

cd "${REPO_DIR}"

# Run your daily pipeline
exec "${VENV_PY}" scripts/run_daily.py --profiles cs,tam,se --us_only
