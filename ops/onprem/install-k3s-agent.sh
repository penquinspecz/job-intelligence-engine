#!/usr/bin/env bash
set -euo pipefail

# Idempotent k3s agent join for on-prem ARM nodes.
K3S_VERSION="${K3S_VERSION:-v1.31.5+k3s1}"
K3S_URL="${K3S_URL:?set K3S_URL, e.g. https://10.0.10.11:6443}"
K3S_TOKEN="${K3S_TOKEN:?set K3S_TOKEN from server node /var/lib/rancher/k3s/server/node-token}"
NODE_NAME="${NODE_NAME:-$(hostname -s)}"

if command -v k3s-agent >/dev/null 2>&1 || systemctl is-active --quiet k3s-agent 2>/dev/null; then
  echo "k3s agent already installed on this host; skipping install"
  systemctl status k3s-agent --no-pager -l || true
  exit 0
fi

echo "Installing k3s agent ${K3S_VERSION} as ${NODE_NAME}"
curl -sfL https://get.k3s.io | \
  K3S_URL="${K3S_URL}" \
  K3S_TOKEN="${K3S_TOKEN}" \
  INSTALL_K3S_VERSION="${K3S_VERSION}" \
  INSTALL_K3S_EXEC="agent --node-name ${NODE_NAME}" \
  sh -

echo "k3s agent installed"
