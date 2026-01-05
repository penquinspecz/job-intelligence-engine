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

