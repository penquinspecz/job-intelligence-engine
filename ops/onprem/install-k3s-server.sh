#!/usr/bin/env bash
set -euo pipefail

# Idempotent k3s server bootstrap for on-prem ARM nodes.
K3S_VERSION="${K3S_VERSION:-v1.31.5+k3s1}"
NODE_NAME="${NODE_NAME:-$(hostname -s)}"
DISABLE_TRAEFIK="${DISABLE_TRAEFIK:-false}"

if command -v k3s >/dev/null 2>&1; then
  echo "k3s already installed on this host; skipping install"
  k3s --version
  exit 0
fi

INSTALL_K3S_EXEC="server --node-name ${NODE_NAME}"
if [[ "${DISABLE_TRAEFIK}" == "true" ]]; then
  INSTALL_K3S_EXEC+=" --disable traefik"
fi

echo "Installing k3s server ${K3S_VERSION} as ${NODE_NAME}"
curl -sfL https://get.k3s.io | \
  INSTALL_K3S_VERSION="${K3S_VERSION}" \
  INSTALL_K3S_EXEC="${INSTALL_K3S_EXEC}" \
  sh -

echo "k3s server installed"
echo "Kubeconfig: /etc/rancher/k3s/k3s.yaml"
