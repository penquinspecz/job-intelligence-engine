# On-Prem Pi Overlay (Exposure-Hardened)

This overlay layers on top of `ops/k8s/overlays/onprem` with ingress hardening for small trusted traffic.

Includes:
- Ingress annotations for conservative rate limiting and security headers
- Traefik middleware chain (`rateLimit` + secure response headers)
- Baseline dashboard `NetworkPolicy` (ingress limited to cluster namespaces)

Notes:
- No secrets are committed here.
- This is cloud-agnostic and intended for k3s on-prem deployments.
- Preferred external exposure is Cloudflare Tunnel/Access, not direct WAN ingress.
