# Runbook: Deploy (On-Prem Path)

## 1) Render and apply on-prem overlay

```bash
python scripts/k8s_render.py --overlay onprem > /tmp/jobintel-onprem.yaml
kubectl apply -f /tmp/jobintel-onprem.yaml
```

Expected cue:
- `namespace/jobintel configured` and CronJob/Deployment created.

## 2) Verify workload objects

```bash
kubectl -n jobintel get cronjob,deploy,svc,pvc
kubectl -n jobintel get pods -o wide
```

Expected cue:
- `jobintel-daily` CronJob exists
- `jobintel-dashboard` deployment available
- PVCs are `Bound`

## 3) Trigger one manual run

```bash
kubectl -n jobintel create job --from=cronjob/jobintel-daily jobintel-manual-$(date +%Y%m%d-%H%M%S)
kubectl -n jobintel get jobs
kubectl -n jobintel logs job/$(kubectl -n jobintel get jobs -o jsonpath='{.items[-1].metadata.name}')
```

## 4) Dashboard ingress (internal)

```bash
kubectl -n jobintel get ingress
kubectl -n jobintel describe ingress jobintel-dashboard
```

TLS strategy:
- internal CA or self-signed cert trusted by VPN clients
- renew certs via your cluster certificate controller process
