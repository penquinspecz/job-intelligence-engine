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
