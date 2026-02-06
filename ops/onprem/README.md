# On-Prem Baseline (k3s on ARM)

This directory is the on-prem operations scaffold for JobIntel primary runtime.

## Golden Path

1. Prepare 3 nodes with static IPs and hostnames (`jobintel-pi1`, `jobintel-pi2`, `jobintel-pi3`).
2. Attach USB3 SSD to the server node and mount it (`ops/onprem/mount-ssd.sh`).
3. Install k3s server (`ops/onprem/install-k3s-server.sh`).
4. Join agent nodes (`ops/onprem/install-k3s-agent.sh`).
5. Deploy manifests from `ops/k8s/jobintel/overlays/onprem`.
6. Access dashboard over VPN + internal TLS.

## Hardware

- Recommended: 3 nodes total.
- Path A: `3 x Raspberry Pi 4 (8GB)`.
- Path B: `2 x Raspberry Pi 4 (8GB) + 1 x Raspberry Pi 5 (8GB)`.
- Storage: USB3 SSD for stateful paths (do not use SD for persistent writes).

## OS

- Preferred: SLE Micro ARM (if your team already operates SUSE tooling).
- Fallback: Ubuntu Server 24.04 LTS ARM.

## Network assumptions

- Layer 2 LAN with static IP reservations.
- Outbound internet allowed for job providers and object-store API.
- Inbound app access over VPN only (Tailscale or WireGuard), no direct WAN exposure.

## Storage choice

- Default storage class: `local-path` (bundled with k3s).
- On-prem overlay provisions PVCs for `/app/state` and `/app/data/ashby_cache`.

## GitOps-ready posture

- All runtime manifests are kustomize resources in repo.
- On-prem overlay path: `ops/k8s/jobintel/overlays/onprem`.
- This is Flux-compatible (`Kustomization` can target the overlay path directly).

## Next docs

- `ops/onprem/RUNBOOK_ONPREM_INSTALL.md`
- `ops/onprem/RUNBOOK_DEPLOY.md`
- `ops/onprem/RUNBOOK_UPGRADES.md`
