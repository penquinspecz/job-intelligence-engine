# Runbook: Upgrades (k3s + JobIntel)

## k3s upgrade (server then agents)

```bash
# On server node
curl -sfL https://get.k3s.io | INSTALL_K3S_VERSION=v1.31.6+k3s1 sh -

# On each agent node
curl -sfL https://get.k3s.io | INSTALL_K3S_VERSION=v1.31.6+k3s1 K3S_URL=https://<server-ip>:6443 K3S_TOKEN=<token> sh -
```

Verify:
```bash
kubectl get nodes -o wide
kubectl -n kube-system get pods
```

## JobIntel app image upgrade

```bash
export JOBINTEL_IMAGE=<registry>/jobintel:<tag>
python scripts/k8s_render.py --overlay onprem --image "$JOBINTEL_IMAGE" > /tmp/jobintel-onprem.yaml
kubectl apply -f /tmp/jobintel-onprem.yaml
kubectl -n jobintel rollout status deploy/jobintel-dashboard
```

## Post-upgrade checks

```bash
kubectl -n jobintel get cronjob jobintel-daily
kubectl -n jobintel create job --from=cronjob/jobintel-daily jobintel-upgrade-smoke-$(date +%Y%m%d-%H%M%S)
kubectl -n jobintel get jobs
```
