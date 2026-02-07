# On-Prem Overlay Contract

This overlay is the canonical on-prem deploy target:

```bash
kubectl apply -k ops/k8s/jobintel/overlays/onprem
```

## What it includes

- `CronJob` (`jobintel-daily`)
- Dashboard deployment/service
- PVCs for persistent `state` and `data` paths
- Ingress resource for dashboard with Traefik class and TLS secret reference

## Storage + database stance

- Primary persisted state is filesystem-backed (`/app/state`, `/app/data/ashby_cache`) on PVCs.
- Postgres is optional and not enabled in this default overlay.
- If you need Postgres on-prem, use `ops/k8s/jobintel/overlays/onprem-postgres`.

## Access strategy

- VPN-first (Tailscale/WireGuard) is required by default.
- Do not expose dashboard/API to WAN without a documented exception.

## TLS strategy

- Ingress expects `jobintel-dashboard-tls` secret.
- Use internal CA or ACME flow compatible with private/VPN DNS.
