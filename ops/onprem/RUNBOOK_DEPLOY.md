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
- Validation receipts: `docs/proof/onprem-ops-hardening-2026-02-13.md`

Apply hardened overlay:

```bash
kubectl apply -k ops/k8s/overlays/onprem-pi
```

Security posture:
- Dashboard artifact reads are constrained to declared run artifacts only.
- Path traversal and malformed artifact mapping are rejected fail-closed.

## 6) Cloudflare Tunnel + Access (recommended runbook)

This section is for exposing dashboard/API to trusted friends without adding in-app auth.

### 6.1 Prerequisites
- Cloudflare-managed DNS zone (for example `signalcraft.example.com`).
- Cloudflare Zero Trust enabled for your account.
- `cloudflared` available either:
  - on a trusted admin host, or
  - as an in-cluster deployment.
- No direct router/NAT forwarding to cluster ingress.

### 6.2 DNS and hostname plan
- Reserve a dedicated hostname for dashboard/API exposure:
  - Example: `jobs.signalcraft.example.com`
- Keep origin internal:
  - in-cluster service DNS (`jobintel-dashboard.jobintel.svc.cluster.local`)
  - or private ingress address on VPN/LAN only

### 6.3 Create tunnel and route DNS

Host-managed tunnel example:

```bash
cloudflared tunnel login
cloudflared tunnel create signalcraft-friends
cloudflared tunnel route dns signalcraft-friends jobs.signalcraft.example.com
```

Example tunnel config (`~/.cloudflared/config.yml`):

```yaml
tunnel: <TUNNEL_UUID>
credentials-file: /etc/cloudflared/<TUNNEL_UUID>.json
ingress:
  - hostname: jobs.signalcraft.example.com
    service: http://jobintel-dashboard.jobintel.svc.cluster.local:80
  - service: http_status:404
```

Run tunnel:

```bash
cloudflared tunnel run signalcraft-friends
```

### 6.4 Optional in-cluster cloudflared manifest example (no secrets in git)

Create token secret out-of-band:

```bash
kubectl -n jobintel create secret generic cloudflared-tunnel \
  --from-literal=TUNNEL_TOKEN='<TOKEN_FROM_CLOUDFLARE>'
```

Manifest example:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: cloudflared
  namespace: jobintel
spec:
  replicas: 1
  selector:
    matchLabels:
      app: cloudflared
  template:
    metadata:
      labels:
        app: cloudflared
    spec:
      containers:
        - name: cloudflared
          image: cloudflare/cloudflared:latest
          args:
            - tunnel
            - --no-autoupdate
            - run
          env:
            - name: TUNNEL_TOKEN
              valueFrom:
                secretKeyRef:
                  name: cloudflared-tunnel
                  key: TUNNEL_TOKEN
```

### 6.5 Cloudflare Access policy baseline
- Create a self-hosted Access application for `jobs.signalcraft.example.com`.
- Policy recommendations:
  - allow only explicit emails/groups (friends allowlist)
  - short session duration
  - require MFA
  - block all by default; no wildcard allow
- Prefer identity-based access for humans.
- Avoid exposing service tokens to non-admin users.

### 6.6 Validation checklist
- Tunnel status healthy:

```bash
cloudflared tunnel info signalcraft-friends
```

- Access enforcement:
  - unauthorized browser request gets Access challenge/deny
  - authorized identity reaches dashboard
- Origin still private:
  - no direct WAN route to cluster ingress/service
  - dashboard only reachable through Tunnel/Access path

### 6.7 Rollback
- Emergency rollback (fastest): disable Access app or tunnel route in Cloudflare dashboard.
- CLI rollback:

```bash
cloudflared tunnel route dns delete signalcraft-friends jobs.signalcraft.example.com
cloudflared tunnel delete signalcraft-friends
```

- Kubernetes rollback (if in-cluster tunnel):

```bash
kubectl -n jobintel delete deploy/cloudflared
kubectl -n jobintel delete secret/cloudflared-tunnel
```

- Fallback temporary access path: short-lived `kubectl port-forward` from trusted admin host only.

Receipt template for future rehearsals:
- `docs/proof/onprem-cloudflare-access-receipt-template.md`

### 6.8 SSRF/Egress safety notes
- SignalCraft currently avoids user-supplied resume/LinkedIn URL ingestion on purpose.
- Reason: user-controlled URLs expand SSRF and uncontrolled egress risk in on-prem deployments.
- Current posture:
  - scrape targets are provider-config driven and policy-bound
  - no arbitrary user URL fetch path exposed in dashboard/API
  - edge auth (Cloudflare Access) protects entry; egress controls protect outbound behavior
