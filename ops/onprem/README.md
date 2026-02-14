# On-Prem Baseline (k3s on ARM)

This directory is the on-prem operations scaffold for SignalCraft primary runtime.

## Golden Path

1. Prepare 3 nodes with static IPs and hostnames (`jobintel-pi1`, `jobintel-pi2`, `jobintel-pi3`).
2. Attach USB3 SSD to the server node and mount it (`ops/onprem/mount-ssd.sh`).
3. Install k3s server (`ops/onprem/install-k3s-server.sh`).
4. Join agent nodes (`ops/onprem/install-k3s-agent.sh`).
5. Rehearse deploy preflights (dry-run, no apply): `make onprem-rehearsal`.
6. Apply manifests only after preflight passes: `kubectl apply -k ops/k8s/overlays/onprem-pi`.
7. Access dashboard over VPN + internal TLS.

Golden Path runbooks:
- Deploy: `ops/onprem/RUNBOOK_DEPLOY.md`
- Managed DNS and exposure posture: `ops/onprem/RUNBOOK_DNS.md`

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

## Friends Exposure (Recommended)

For trusted friends traffic, preferred posture is:
- Cloudflare Tunnel + Cloudflare Access as edge auth
- Cluster service remains private (`ClusterIP`)
- No direct WAN ingress/NAT to dashboard

Operational guide:
- `ops/onprem/RUNBOOK_DEPLOY.md` (section: Cloudflare Tunnel + Access)
- `ops/onprem/RUNBOOK_DNS.md` (managed DNS + hostname posture)

Security constraints to keep:
- No in-app authentication is added in this phase; identity/auth is enforced at the edge.
- No resume/LinkedIn URL ingestion path yet; this is intentionally deferred to avoid opening SSRF and uncontrolled egress vectors.
- Scrape/fetch behavior remains provider-config driven, not user-URL driven.

## Storage choice

- Default storage class: `local-path` (bundled with k3s).
- Default `local-path-provisioner` path on k3s is `/var/lib/rancher/k3s/storage`.
- For write-heavy state, point provisioner paths to SSD/NVMe mountpoints (for example `/mnt/nvme0n1/k3s-storage`), not SD cards.
- On-prem overlay provisions PVCs for `/app/state` and `/app/data/ashby_cache`.

## Node labels strategy

- Label nodes by capability (for example `node.kubernetes.io/class=pi5` and `node.kubernetes.io/class=pi4`).
- Keep heavier scrape/index workloads on Pi5-class nodes via `nodeSelector`/affinity in overlay patches.
- Keep dashboard and lighter control-plane workloads schedulable on mixed nodes for resilience.

## Rollback notes

- Keep deploys declarative (`kubectl apply -k`) so rollback is a known-good git revision + re-apply.
- For edge exposure rollback, use the Cloudflare rollback section in `ops/onprem/RUNBOOK_DEPLOY.md`.
- For cluster/runtime rollback, follow `ops/onprem/RUNBOOK_UPGRADES.md`.

## GitOps-ready posture

- All runtime manifests are kustomize resources in repo.
- On-prem Pi overlay path: `ops/k8s/overlays/onprem-pi`.
- This is Flux-compatible (`Kustomization` can target the overlay path directly).

## Next docs

- `ops/onprem/RUNBOOK_ONPREM_INSTALL.md`
- `ops/onprem/RUNBOOK_DEPLOY.md`
- `ops/onprem/RUNBOOK_DNS.md`
- `ops/onprem/RUNBOOK_UPGRADES.md`
- `ops/onprem/RUNBOOK_BACKUPS.md`
- `ops/onprem/RUNBOOK_BORING_72H_PROOF.md`
- `ops/dr/RUNBOOK_DISASTER_RECOVERY.md`
- `docs/proof/onprem-cloudflare-access-receipt-template.md`

## Milestone 4 prove-it bundle

```bash
python scripts/ops/prove_it_m4.py \
  --plan \
  --run-id m4-plan \
  --output-dir ops/proof/bundles \
  --aws-region us-east-1 \
  --backup-bucket <bucket> \
  --backup-prefix <prefix>/backups/m4-plan \
  --backup-uri s3://<bucket>/<prefix>/backups/m4-plan
```

## 72h proof harness (plan-first)

```bash
python scripts/ops/prove_m4_onprem.py \
  --run-id 20260207T120000Z \
  --output-dir ops/proof/bundles \
  --namespace jobintel \
  --cluster-context <k3s-context>
```

Capture baseline evidence (execute-explicit):

```bash
python scripts/ops/prove_m4_onprem.py \
  --run-id 20260207T120000Z \
  --output-dir ops/proof/bundles \
  --namespace jobintel \
  --cluster-context <k3s-context> \
  --execute
```
