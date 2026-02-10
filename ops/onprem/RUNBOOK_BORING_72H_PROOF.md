# Runbook: 72h Boring Proof (On-Prem k3s)

Use this to produce Milestone 4 on-prem stability receipts without manual drift.

## Preflight checks

Copy/paste commands:

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

Copy/paste commands:

```bash
python scripts/ops/prove_m4_onprem.py \
  --run-id 20260207T120000Z \
  --output-dir ops/proof/bundles \
  --namespace jobintel \
  --cluster-context k3s-pi \
  --overlay-path ops/k8s/jobintel/overlays/onprem
```

Expected receipts:
- `ops/proof/bundles/m4-<run_id>/onprem/checklist.json`
- `ops/proof/bundles/m4-<run_id>/onprem/receipt.json`
- `ops/proof/bundles/m4-<run_id>/onprem/manifest.json`
- `ops/proof/bundles/m4-<run_id>/onprem/capture_commands.sh`
- `ops/proof/bundles/m4-<run_id>/onprem/host_timesync_evidence.txt`
- `ops/proof/bundles/m4-<run_id>/onprem/host_storage_evidence.txt`
- `ops/proof/bundles/m4-<run_id>/onprem/proof_observations.md`

## 1b) Start 72h stability receipt bundle (plan mode)

Copy/paste commands:

```bash
python scripts/ops/capture_onprem_stability_receipts.py --plan \
  --run-id 20260207T120000Z \
  --output-dir ops/proof/bundles \
  --namespace jobintel \
  --cluster-context k3s-pi \
  --window-hours 72 \
  --interval-minutes 360
```

Expected receipts:
- `ops/proof/bundles/m4-<run_id>/onprem-72h/plan.json`
- `ops/proof/bundles/m4-<run_id>/onprem-72h/README.md`
- `ops/proof/bundles/m4-<run_id>/onprem-72h/host_timesync_evidence.txt`
- `ops/proof/bundles/m4-<run_id>/onprem-72h/host_k3s_service_evidence.txt`
- `ops/proof/bundles/m4-<run_id>/onprem-72h/host_storage_evidence.txt`
- `ops/proof/bundles/m4-<run_id>/onprem-72h/ingress_dns_tls_evidence.txt`
- `ops/proof/bundles/m4-<run_id>/onprem-72h/proof_observations.md`

## 2) Capture baseline cluster state

Copy/paste commands:

```bash
python scripts/ops/prove_m4_onprem.py \
  --run-id 20260207T120000Z \
  --output-dir ops/proof/bundles \
  --namespace jobintel \
  --cluster-context k3s-pi \
  --execute
```

Additional receipts written:
- `nodes_wide.log`
- `node_conditions.json`
- `node_notready_events.log`
- `kube_system_pods.log`
- `kube_system_restarts.log`
- `node_leases.log`
- `pods_wide.log`
- `jobs.log`
- `workloads.log`
- `cronjob_history.log`
- `cronjob_describe.log`
- `events.log`
- `restarts.log`
- `proof_observations.md` (72h checkpoint template)
- `host_timesync_evidence.txt` (operator fills with host command outputs)
- `host_storage_evidence.txt` (operator fills with host command outputs)
- `receipt.json` (includes `started_at`, `finished_at`, `captured_at`, `k8s_context`, and `evidence_paths`)

## 2b) Capture stability checkpoint (trial run)

Copy/paste commands:

```bash
python scripts/ops/capture_onprem_stability_receipts.py --execute \
  --run-id 20260207T120000Z \
  --output-dir ops/proof/bundles \
  --namespace jobintel \
  --cluster-context k3s-pi \
  --checkpoint-index 0
```

Success criteria:
- One checkpoint written under `onprem-72h/checkpoints/checkpoint-000/summary.json`.
- `receipt.json` shows `status=fail` only if evidence is missing or health is bad.

If it fails:
- inspect `onprem-72h/receipt.json` fail_reasons
- ensure kubectl context is correct and nodes are Ready

## 3) Observe for 72h and append operator notes

Checkpoint template (copy/paste into `proof_observations.md`):

```markdown
### T+00h
- timestamp_utc:
- node_ready_count:
- notready_nodes:
- control_plane_restarts_delta:
- cronjob_recent_runs_ok:
- pvc_bound_count:
- ingress_tls_ok:
- notes:

### T+24h
- timestamp_utc:
- node_ready_count:
- notready_nodes:
- control_plane_restarts_delta:
- cronjob_recent_runs_ok:
- pvc_bound_count:
- ingress_tls_ok:
- notes:

### T+48h
- timestamp_utc:
- node_ready_count:
- notready_nodes:
- control_plane_restarts_delta:
- cronjob_recent_runs_ok:
- pvc_bound_count:
- ingress_tls_ok:
- notes:

### T+72h
- timestamp_utc:
- node_ready_count:
- notready_nodes:
- control_plane_restarts_delta:
- cronjob_recent_runs_ok:
- pvc_bound_count:
- ingress_tls_ok:
- notes:
```

At minimum collect:
- node readiness stability snapshots
- control-plane pod restart trends (`kube-system`)
- pod restart counts
- CronJob run completions over time
- time sync checks per node
- USB-vs-SD storage mount evidence per node
- ingress/TLS access checks over VPN

Recommended commands (run periodically):

Copy/paste commands:

```bash
kubectl --context k3s-pi get nodes -o wide
kubectl --context k3s-pi -n jobintel get pods -o custom-columns=NAME:.metadata.name,RESTARTS:.status.containerStatuses[*].restartCount
kubectl --context k3s-pi -n jobintel get jobs --sort-by=.metadata.creationTimestamp
kubectl --context k3s-pi -n jobintel get events --sort-by=.metadata.creationTimestamp | tail -n 80
```

Update `proof_observations.md` at each checkpoint (`T+00h`, `T+24h`, `T+48h`, `T+72h`) so the final bundle has an explicit operator narrative linked to raw logs.

## 3b) Run the 72h stability loop (recommended)

Copy/paste commands:

```bash
python scripts/ops/capture_onprem_stability_receipts.py --execute --loop \
  --run-id 20260207T120000Z \
  --output-dir ops/proof/bundles \
  --namespace jobintel \
  --cluster-context k3s-pi \
  --window-hours 72 \
  --interval-minutes 360
```

If SSH access is available, add `--ssh-host` for each node (and optional `--ssh-user`)
to auto-capture k3s service status, time sync, and storage evidence. Otherwise fill the
host evidence templates manually and re-run finalize.

Finalize (after host evidence is filled):

```bash
python scripts/ops/capture_onprem_stability_receipts.py --finalize \
  --run-id 20260207T120000Z \
  --output-dir ops/proof/bundles \
  --namespace jobintel \
  --cluster-context k3s-pi
```

If you must finalize without host evidence (not recommended), pass:

```bash
python scripts/ops/capture_onprem_stability_receipts.py --finalize \
  --allow-missing-host-evidence \
  --run-id 20260207T120000Z \
  --output-dir ops/proof/bundles \
  --namespace jobintel \
  --cluster-context k3s-pi
```

Note: avoid angle brackets in copy/paste examples; many shells (including zsh) interpret them.

## 4) Failure branches

- If nodes flap `NotReady`: inspect node pressure, k3s service logs, and network link stability.
- If CronJob misses runs: inspect CronJob schedule/timezone and controller events.
- If restarts spike: inspect offending pod `describe` and recent config/image changes.
- If ingress fails: verify Traefik, DNS on VPN, and TLS secret validity.
