# Managed DNS Runbook (Pi Cluster)

This runbook covers DNS and exposure posture for SignalCraft on a home/lab Pi cluster.

## Scope

- Cluster: k3s on Raspberry Pi nodes (Pi4/Pi5 mix)
- DNS: managed provider (registrar DNS, Cloudflare, etc.)
- Goal: reliable operator access with safe remote sharing

## Non-Negotiable Security Posture

- Do not expose dashboard/API unauthenticated to the public internet.
- Prefer edge-authenticated access (Cloudflare Tunnel + Access).
- Keep in-cluster services private (`ClusterIP`) where possible.
- No secrets in git; keep tokens/credentials in external secret stores.

## Hostname Strategy

Use deterministic hostnames to separate local and remote entrypoints.

- LAN/internal:
  - `signalcraft.lan` (or local DNS equivalent)
  - Optional per-surface names: `dash.signalcraft.lan`, `api.signalcraft.lan`
- Remote (managed DNS):
  - `signalcraft.<your-domain>`
  - Optional split: `dash.<your-domain>`, `api.<your-domain>`

Guideline:
- LAN names resolve to local ingress IP.
- Remote names terminate at edge access (Tunnel/Access), not direct node ports.

## LAN vs Remote Access

### LAN Access

- Use local DNS or static host mapping inside trusted network.
- Keep ingress reachable only on LAN/VPN.
- Treat LAN access as operator-only.

### Remote Access (Recommended)

Use Cloudflare Tunnel + Access for remote users.

Why:
- Avoids direct inbound NAT/port-forward exposure.
- Adds identity-aware access policy before traffic hits cluster.
- Supports auditable, revocable access without in-app auth changes.

Reference:
- `ops/onprem/RUNBOOK_DEPLOY.md`
- `ops/onprem/README.md` (friends exposure posture)

## TLS Certificate Strategy (High Level)

- Preferred for public hostnames: ACME DNS-01 challenge with managed DNS provider.
- For private-only LAN hostnames: internal CA or trusted local cert distribution.
- Do not commit certificates, private keys, API tokens, or ACME account material.

## Pi Cluster Guardrails

- Back up PVC-backed data (`/app/state`, `/app/data/ashby_cache`) on a schedule.
- Keep SD cards out of write-heavy paths; use SSD/NVMe for persistent workloads.
- Label nodes by capability and pin heavy workloads to Pi5 class nodes.
  - Example labels: `node.kubernetes.io/class=pi5`, `node.kubernetes.io/class=pi4`
  - Use affinity/nodeSelector in overlays for scrape/index heavy jobs.

## CNCF-ish Operating Pattern

- Declarative manifests (`kustomize`) as source of truth.
- Reproducible apply/rollback flow from git state.
- CronJob-first operations with artifact receipts.
- Cloud-agnostic posture: on-prem primary with portable patterns.

## Preflight Checks

- Confirm cluster ingress is healthy and not directly exposed to WAN.
- Confirm managed DNS records point to edge entrypoints (Tunnel/Access), not node public IPs.
- Confirm Access policy is enabled before sharing remote URL.

```bash
kubectl get ingress -A
kubectl get svc -n jobintel
kubectl get pods -n jobintel
```

## Success Criteria

- Remote access requires edge authentication (Cloudflare Access or equivalent).
- No direct unauthenticated internet route to dashboard/API.
- Hostnames resolve consistently for LAN and remote paths.
- PVC backup schedule is active and recent restore checks exist.

## If It Fails

- If DNS resolution is wrong: correct provider records and re-check propagation.
- If remote access bypasses edge auth: disable public route immediately and route through Tunnel/Access.
- If cert issuance fails: verify DNS challenge permissions and provider API token scope.
- If Pi nodes are unstable under load: move write-heavy workloads to Pi5/SSD-backed nodes and reduce SD writes.
