# Runbook: 72h Boring Proof (On-Prem k3s)

Use this to produce Milestone 4 on-prem stability receipts without manual drift.

## Preflight checks

```bash
kubectl config current-context
kubectl get nodes -o wide
kubectl -n jobintel get cronjob,deploy,pvc,ingress
```

Success criteria:
- Context is correct cluster.
- Nodes are `Ready`.
- On-prem overlay objects are present.

## 1) Start proof bundle in plan mode (safe default)

```bash
python scripts/ops/prove_m4_onprem.py \
  --run-id 20260207T120000Z \
  --output-dir ops/proof/bundles \
  --namespace jobintel \
  --cluster-context <k3s-context> \
  --overlay-path ops/k8s/jobintel/overlays/onprem
```

Expected receipts:
- `ops/proof/bundles/m4-<run_id>/onprem/checklist.json`
- `ops/proof/bundles/m4-<run_id>/onprem/receipt.json`
- `ops/proof/bundles/m4-<run_id>/onprem/manifest.json`

## 2) Capture baseline cluster state

```bash
python scripts/ops/prove_m4_onprem.py \
  --run-id 20260207T120000Z \
  --output-dir ops/proof/bundles \
  --namespace jobintel \
  --cluster-context <k3s-context> \
  --execute
```

Additional receipts written:
- `nodes_wide.log`
- `workloads.log`
- `events.log`
- `restarts.log`

## 3) Observe for 72h and append operator notes

At minimum collect:
- node readiness stability snapshots
- pod restart counts
- CronJob run completions
- ingress/TLS access checks over VPN

Recommended commands (run periodically):

```bash
kubectl --context <k3s-context> get nodes -o wide
kubectl --context <k3s-context> -n jobintel get pods -o custom-columns=NAME:.metadata.name,RESTARTS:.status.containerStatuses[*].restartCount
kubectl --context <k3s-context> -n jobintel get jobs --sort-by=.metadata.creationTimestamp
kubectl --context <k3s-context> -n jobintel get events --sort-by=.metadata.creationTimestamp | tail -n 80
```

## 4) Failure branches

- If nodes flap `NotReady`: inspect node pressure, k3s service logs, and network link stability.
- If CronJob misses runs: inspect CronJob schedule/timezone and controller events.
- If restarts spike: inspect offending pod `describe` and recent config/image changes.
- If ingress fails: verify Traefik, DNS on VPN, and TLS secret validity.
