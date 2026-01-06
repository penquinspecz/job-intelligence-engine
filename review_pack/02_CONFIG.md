# Config & Ops
Included: `src/ji_engine/config.py`, `config/profiles.json` (see 12_SCORING for details), launchd assets (`ops/launchd/com.chris.jobintel.plist`, `install.sh`, `run_jobintel.sh`).

Why they matter: central paths for artifacts, profile defaults, and operational scheduling/install scripts.

Omitted: none (full contents below).

## src/ji_engine/config.py
```
from __future__ import annotations

from pathlib import Path

# Base directories
REPO_ROOT = Path(".")
DATA_DIR = REPO_ROOT / "data"
STATE_DIR = DATA_DIR / "state"
SNAPSHOT_DIR = DATA_DIR / "openai_snapshots"

# Canonical pipeline artifacts
RAW_JOBS_JSON = DATA_DIR / "openai_raw_jobs.json"
LABELED_JOBS_JSON = DATA_DIR / "openai_labeled_jobs.json"
ENRICHED_JOBS_JSON = DATA_DIR / "openai_enriched_jobs.json"
ASHBY_CACHE_DIR = DATA_DIR / "ashby_cache"

RANKED_FAMILIES_JSON = DATA_DIR / "openai_ranked_families.json"

def ranked_jobs_json(profile: str) -> Path:
    return DATA_DIR / f"openai_ranked_jobs.{profile}.json"

def ranked_jobs_csv(profile: str) -> Path:
    return DATA_DIR / f"openai_ranked_jobs.{profile}.csv"

def ranked_families_json(profile: str) -> Path:
    return DATA_DIR / f"openai_ranked_families.{profile}.json"

def shortlist_md(profile: str) -> Path:
    return DATA_DIR / f"openai_shortlist.{profile}.md"

def state_last_ranked(profile: str) -> Path:
    return STATE_DIR / f"last_ranked.{profile}.json"

LOCK_PATH = STATE_DIR / "run_daily.lock"
```

## ops/launchd/com.chris.jobintel.plist
```
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.chris.jobintel</string>

    <key>ProgramArguments</key>
    <array>
        <string>/Users/christophermenendez/Projects/job-intelligence-engine/.venv/bin/python</string>
        <string>scripts/run_daily.py</string>
        <string>--profiles</string>
        <string>cs,tam,se</string>
        <string>--us_only</string>
        <string>--min_alert_score</string>
        <string>85</string>
    </array>

    <key>WorkingDirectory</key>
    <string>/Users/christophermenendez/Projects/job-intelligence-engine</string>

    <key>EnvironmentVariables</key>
    <dict>
        <key>CAREERS_MODE</key>
        <string>AUTO</string>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
        <key>PYTHONPATH</key>
        <string>/Users/christophermenendez/Projects/job-intelligence-engine/src</string>
    </dict>

    <key>RunAtLoad</key>
    <true/>

    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>9</integer>
        <key>Minute</key>
        <integer>5</integer>
    </dict>

    <key>StandardOutPath</key>
    <string>/tmp/jobintel.out.log</string>

    <key>StandardErrorPath</key>
    <string>/tmp/jobintel.err.log</string>
</dict>
</plist>
```

## ops/launchd/install.sh
```
#!/usr/bin/env bash
set -euo pipefail

PLIST_SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/com.chris.jobintel.plist"
PLIST_DEST="${HOME}/Library/LaunchAgents/com.chris.jobintel.plist"

echo "Installing launch agent to ${PLIST_DEST}"
mkdir -p "${HOME}/Library/LaunchAgents"
cp "${PLIST_SRC}" "${PLIST_DEST}"

echo "Reloading launch agent..."
launchctl unload "${PLIST_DEST}" >/dev/null 2>&1 || true
launchctl load "${PLIST_DEST}"

echo "Done."
echo
echo "To check status: launchctl list | grep com.chris.jobintel"
echo "To tail logs: tail -f /tmp/jobintel.out.log /tmp/jobintel.err.log"
```

## ops/launchd/run_jobintel.sh
```
#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VENV_PY="${REPO_DIR}/.venv/bin/python"

cd "${REPO_DIR}"

# Run your daily pipeline
exec "${VENV_PY}" scripts/run_daily.py --profiles cs,tam,se --us_only
```

