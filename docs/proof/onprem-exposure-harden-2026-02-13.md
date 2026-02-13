# On-Prem Exposure Hardening Receipt (2026-02-13)

## Goal
Harden on-prem dashboard/API exposure for trusted "friends traffic" while reducing exfil risk.

## Recommended setup (exact steps)

1. Render and review hardened overlay:

```bash
kubectl kustomize ops/k8s/overlays/onprem-pi
```

2. Apply hardened overlay:

```bash
kubectl apply -k ops/k8s/overlays/onprem-pi
```

3. Preferred exposure path: Cloudflare Tunnel + Access
- Keep `jobintel-dashboard` service internal (`ClusterIP`).
- Publish through Cloudflare Tunnel only.
- Enforce Access policy (explicit allowlist identities).
- Do not expose ingress directly to WAN via router/NAT.

4. Alternative (temporary): local `port-forward` from trusted admin host

```bash
kubectl -n jobintel port-forward svc/jobintel-dashboard 8080:80
```

- Restrict host firewall to explicit source IPs only.
- Tear down forwarding after use.

5. Verify ingress hardening controls are present:
- Ingress annotations include rate limiting and secure headers.
- Traefik middleware chain (`dashboard-security-chain`) is attached.
- `NetworkPolicy` baseline limits dashboard ingress scope.

## Security controls added

- `ops/k8s/overlays/onprem-pi/patch-ingress-dashboard-security.yaml`
  - Rate limit + secure header annotations.
- `ops/k8s/overlays/onprem-pi/traefik-dashboard-middleware.yaml`
  - Traefik middleware chain for rate limiting and response hardening.
- `ops/k8s/overlays/onprem-pi/networkpolicy-dashboard.yaml`
  - Baseline ingress isolation policy for dashboard pods.
- Dashboard API artifact guard hardening:
  - `/runs/{run_id}/artifact/{name}` now rejects path separators and invalid mapping paths.
  - Artifact reads are constrained to index-declared artifact names only.

## Validation output

- `kubectl kustomize ops/k8s/overlays/onprem-pi` → rendered (`561` lines)
- `scripts/k8s_render.py --overlay onprem-pi` → rendered (`562` lines)
- `make format` → pass
- `make lint` → pass
- `pytest -q` (local env) → fails due botocore CRT login-provider dependency in existing publish tests
- `AWS_CONFIG_FILE=/dev/null AWS_SHARED_CREDENTIALS_FILE=/dev/null AWS_EC2_METADATA_DISABLED=true PYTHONPATH=src ./.venv/bin/python -m pytest -q` → `509 passed, 15 skipped`
