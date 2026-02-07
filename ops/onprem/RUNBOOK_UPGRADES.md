# Runbook: Upgrades (k3s + JobIntel)

## Preflight checks

```bash
kubectl get nodes -o wide
kubectl -n kube-system get pods
kubectl -n jobintel get cronjob,deploy,pvc
```

Success criteria:
- Cluster healthy before upgrade.
- No unresolved CrashLoopBackOff in core components.

If it fails:
- Stop and stabilize cluster before applying any version change.

## 1) k3s upgrade (server first, then agents)

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

Success criteria:
- All nodes return to `Ready`.
- Control-plane add-ons recover without repeated restarts.

If it fails:
- `journalctl -u k3s -n 200 --no-pager` (server)
- `journalctl -u k3s-agent -n 200 --no-pager` (agents)
- rollback by reinstalling previous known-good k3s version.

## 2) JobIntel image upgrade

```bash
export JOBINTEL_IMAGE=<registry>/jobintel:<tag>
python scripts/k8s_render.py --overlay onprem --image "$JOBINTEL_IMAGE" > /tmp/jobintel-onprem.yaml
kubectl apply -f /tmp/jobintel-onprem.yaml
kubectl -n jobintel rollout status deploy/jobintel-dashboard --timeout=5m
```

Success criteria:
- Dashboard rollout completes.
- CronJob spec reflects updated image.

If it fails:
- `kubectl -n jobintel describe deploy jobintel-dashboard`
- `kubectl -n jobintel logs deploy/jobintel-dashboard --tail=200`

## 3) Post-upgrade smoke

```bash
RUN_NAME=jobintel-upgrade-smoke-$(date +%Y%m%d-%H%M%S)
kubectl -n jobintel create job --from=cronjob/jobintel-daily "$RUN_NAME"
kubectl -n jobintel wait --for=condition=complete "job/$RUN_NAME" --timeout=20m
kubectl -n jobintel logs "job/$RUN_NAME" | tail -n 120
```

Success criteria:
- One full job run succeeds after upgrade.
- No PVC regressions (`kubectl -n jobintel get pvc` remains `Bound`).
