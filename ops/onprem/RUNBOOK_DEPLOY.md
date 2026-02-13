# Runbook: Deploy (On-Prem Primary Path)

## Preflight checks

```bash
kubectl config current-context
kubectl get nodes
kubectl -n jobintel get secret jobintel-secrets
```

Success criteria:
- Context is the intended k3s cluster.
- Nodes are `Ready`.
- `jobintel-secrets` exists (created out-of-band; no plaintext secrets in repo).

If it fails:
- Re-select context and re-run.
- If secret missing: create from secret manager material before deploy.

## 1) One-command deploy (kustomize source of truth)

```bash
kubectl apply -k ops/k8s/jobintel/overlays/onprem
```

Success criteria:
- Apply exits zero and creates/updates namespace resources.

If it fails:
- `kubectl kustomize ops/k8s/jobintel/overlays/onprem | head -n 80`
- `kubectl -n jobintel get events --sort-by=.metadata.creationTimestamp | tail -n 50`

## 2) Verify CronJob + dashboard + persistence

```bash
kubectl -n jobintel get cronjob,deploy,svc,pvc,ingress -o wide
kubectl -n jobintel get pods -o wide
```

Success criteria:
- `jobintel-daily` CronJob exists.
- `jobintel-dashboard` deployment available.
- `jobintel-state-pvc` and `jobintel-data-pvc` are `Bound`.

If it fails:
- `kubectl -n jobintel describe pvc jobintel-state-pvc`
- `kubectl -n jobintel describe deploy jobintel-dashboard`

## 3) Trigger one manual job run

```bash
RUN_NAME=jobintel-manual-$(date +%Y%m%d-%H%M%S)
kubectl -n jobintel create job --from=cronjob/jobintel-daily "$RUN_NAME"
kubectl -n jobintel wait --for=condition=complete "job/$RUN_NAME" --timeout=20m
kubectl -n jobintel logs "job/$RUN_NAME" | tail -n 120
```

Success criteria:
- Job completes successfully.
- Logs include `JOBINTEL_RUN_ID=` and run pipeline summary lines.

If it fails:
- `kubectl -n jobintel describe job "$RUN_NAME"`
- `kubectl -n jobintel get pods -l job-name="$RUN_NAME" -o wide`

## 4) Dashboard access (VPN + internal TLS)

```bash
kubectl -n jobintel get ingress jobintel-dashboard -o yaml
kubectl -n jobintel describe ingress jobintel-dashboard
kubectl -n jobintel get secret jobintel-dashboard-tls
```

Success criteria:
- Ingress host resolves on VPN.
- TLS secret exists and is referenced by ingress.

If it fails:
- If host does not resolve: fix VPN DNS route first.
- If TLS secret missing: provision cert and recreate secret before exposing endpoint.

## 5) Exposure pattern (friends traffic hardening)

Preferred pattern: Cloudflare Tunnel + Cloudflare Access
- Keep cluster service private (`ClusterIP` only).
- Terminate external access in Cloudflare Zero Trust policies.
- Restrict by identity/email allowlist and device posture where available.
- Keep origin host private (no direct WAN listener/NAT rule to ingress).

Alternative pattern: local-only `kubectl port-forward` + host firewall
- Use short-lived forwarding from a trusted admin host:

```bash
kubectl -n jobintel port-forward svc/jobintel-dashboard 8080:80
```

- Restrict host firewall to explicit source IPs only.
- Do not expose dashboard via open router port forwarding.

Baseline technical controls shipped in `onprem-pi` overlay:
- Ingress rate limiting annotations + secure headers
- Traefik middleware chain for response hardening
- Dashboard ingress `NetworkPolicy` baseline (CNI enforcement required)

Apply hardened overlay:

```bash
kubectl apply -k ops/k8s/overlays/onprem-pi
```

Security posture:
- Dashboard artifact reads are constrained to declared run artifacts only.
- Path traversal and malformed artifact mapping are rejected fail-closed.
