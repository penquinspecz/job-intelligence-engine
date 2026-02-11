# JobIntel K8s Runbook (Milestone 2)

This runbook is **K8s-first** and copy/pasteable. It covers deploy, inspect last run, rollback, and secret rotation.

## Preflight checks

```bash
kubectl config current-context
kubectl get nodes -o wide
kubectl -n jobintel get cronjob,deploy,serviceaccount,configmap
```

## Success criteria

- CronJob and dashboard resources apply cleanly.
- One-off run emits `JOBINTEL_RUN_ID` and writes proof artifacts.
- Publish verification succeeds for the selected run id.

## If it fails

- Stop before retrying apply loops.
- Capture `kubectl describe` and recent events first.
- Follow the Troubleshooting section in this runbook for targeted recovery commands.

## Golden Path (10 Commands)

```bash
export KUBE_CONTEXT="<kube_context>"
export NAMESPACE="jobintel"
export BUCKET="<s3_bucket>"
export PREFIX="jobintel"

python scripts/k8s_render.py --overlay eks > /tmp/jobintel.yaml
kubectl --context "$KUBE_CONTEXT" apply -f /tmp/jobintel.yaml
kubectl --context "$KUBE_CONTEXT" -n "$NAMESPACE" get cronjob jobintel-daily
kubectl --context "$KUBE_CONTEXT" -n "$NAMESPACE" create job --from=cronjob/jobintel-daily jobintel-manual-$(date +%Y%m%d)
kubectl --context "$KUBE_CONTEXT" -n "$NAMESPACE" logs -f job/jobintel-manual-$(date +%Y%m%d)
python scripts/prove_cloud_run.py --bucket "$BUCKET" --prefix "$PREFIX" --namespace "$NAMESPACE" --job-name jobintel-manual-$(date +%Y%m%d)
python scripts/verify_published_s3.py --bucket "$BUCKET" --run-id "<run_id>" --prefix "$PREFIX" --verify-latest
cat state/proofs/<run_id>.json
kubectl --context "$KUBE_CONTEXT" -n "$NAMESPACE" get jobs
```

Expected cues:
- Logs include `JOBINTEL_RUN_ID=<run_id>`.
- `state/proofs/<run_id>.json` exists locally.
- `verify_published_s3` prints `ok`.

---

## Prereqs

- `kubectl` context set: `kubectl config current-context`
- EKS auth works: `aws eks update-kubeconfig --name <cluster> --region <region>`
- Image pushed and pullable by the cluster (no `ImagePullBackOff`).
- S3 bucket exists and IRSA role has publish permissions.
- Secrets created (see “Rotate secrets”).

## Deploy (Base + Overlays)

Render and apply:

```bash
python scripts/k8s_render.py --overlay eks > /tmp/jobintel.yaml
kubectl --context "$KUBE_CONTEXT" apply -f /tmp/jobintel.yaml
```

Verify CronJob:

```bash
kubectl --context "$KUBE_CONTEXT" -n "$NAMESPACE" get cronjob jobintel-daily
kubectl --context "$KUBE_CONTEXT" -n "$NAMESPACE" get cronjob jobintel-daily -o yaml | rg -n "image:|CAREERS_MODE|PUBLISH_S3"
```

## Dashboard API (EKS-safe, no ingress required)

Apply base + AWS overlay (includes dashboard deployment + service):

```bash
export JOBINTEL_IMAGE="<acct>.dkr.ecr.<region>.amazonaws.com/jobintel:<tag>"
export JOBINTEL_IRSA_ROLE_ARN="<arn:aws:iam::<account_id>:role/<irsa_role_name>>"
: "${JOBINTEL_IRSA_ROLE_ARN:?set JOBINTEL_IRSA_ROLE_ARN to a non-empty IRSA role ARN}"
python scripts/k8s_render.py --overlay eks --image "$JOBINTEL_IMAGE" > /tmp/jobintel.yaml
kubectl --context "$KUBE_CONTEXT" apply -f /tmp/jobintel.yaml
kubectl --context "$KUBE_CONTEXT" -n "$NAMESPACE" get deploy jobintel-dashboard
```

Port-forward locally:

```bash
kubectl --context "$KUBE_CONTEXT" -n "$NAMESPACE" port-forward svc/jobintel-dashboard 8080:80
curl -s http://localhost:8080/healthz
```

No-secrets path (read-only):
- `jobintel-secrets` is optional for the dashboard deployment.
- Without secrets, `/healthz` is available; S3-backed browsing is not configured by default.

## Verify Deployment (Scheduled + One-off)

Check schedule:

```bash
kubectl --context "$KUBE_CONTEXT" -n "$NAMESPACE" get cronjob jobintel-daily -o jsonpath='{.status.lastScheduleTime}'
```

Run a one-off job:

```bash
kubectl --context "$KUBE_CONTEXT" -n "$NAMESPACE" \
  create job --from=cronjob/jobintel-daily jobintel-manual-$(date +%Y%m%d)
```

## Inspect Last Run

Find latest Job and Pod:

```bash
kubectl --context "$KUBE_CONTEXT" -n "$NAMESPACE" get jobs --sort-by=.status.startTime
LATEST_JOB="$(kubectl --context "$KUBE_CONTEXT" -n "$NAMESPACE" get jobs --sort-by=.status.startTime -o jsonpath='{.items[-1].metadata.name}')"
POD_NAME="$(kubectl --context "$KUBE_CONTEXT" -n "$NAMESPACE" get pods -l "job-name=${LATEST_JOB}" -o jsonpath='{.items[0].metadata.name}')"
```

Tail logs and extract run id:

```bash
kubectl --context "$KUBE_CONTEXT" -n "$NAMESPACE" logs -f "job/${LATEST_JOB}"
kubectl --context "$KUBE_CONTEXT" -n "$NAMESPACE" logs "job/${LATEST_JOB}" | rg -n "JOBINTEL_RUN_ID="
```

Proof capture (local):

```bash
python scripts/prove_cloud_run.py \
  --bucket "$BUCKET" \
  --prefix "$PREFIX" \
  --namespace "$NAMESPACE" \
  --job-name "$LATEST_JOB"
cat state/proofs/<run_id>.json
```

Optional live proof (enforces live provenance checks + writes log):

```bash
NS="$NAMESPACE" bash scripts/prove_live_scrape_eks.sh
cat ops/proof/liveproof-<run_id>.log
```

Single-command receipts driver (recommended):

```bash
python scripts/prove_it_m3.py \
  --cluster-name "<cluster_name>" \
  --context "$KUBE_CONTEXT" \
  --namespace "$NAMESPACE" \
  --bucket "$BUCKET" \
  --prefix "$PREFIX" \
  --write-excerpt
```

Expected bundle:
- `ops/proof/bundles/m3-<run_id>/liveproof-<run_id>.log`
- `ops/proof/bundles/m3-<run_id>/verify_published_s3-<run_id>.log`
- `ops/proof/bundles/m3-<run_id>/proofs/<run_id>.json`
- `ops/proof/bundles/m3-<run_id>/bundle_manifest.json`
- Optional: `ops/proof/bundles/m3-<run_id>/liveproof-<run_id>.excerpt.log`

## EKS connectivity proof (one-command)

### Preflight checks

- Ensure the cluster context is set: `kubectl config use-context eks-jobintel-eks`
- Ensure `AWS_PROFILE=jobintel-deployer` and caller is not root:
  - `AWS_PROFILE=jobintel-deployer aws sts get-caller-identity`

### Execute (single command)

```bash
AWS_PROFILE=jobintel-deployer python scripts/ops/capture_eks_connectivity_receipts.py --execute \
  --run-id m4-eks-proof-<UTCSTAMP> \
  --output-dir ops/proof/bundles \
  --cluster-context eks-jobintel-eks \
  --namespace jobintel
```

### Success criteria

- `ops/proof/bundles/m4-<run_id>/eks/receipt.json` exists.
- Receipt includes: `run_id`, `cluster_context`, `namespace`, `status`, `evidence_files`.

### If it fails

- **Unauthorized**: confirm `AWS_PROFILE=jobintel-deployer` and caller ARN is not `...:root`.
- **Wrong context**: `kubectl config current-context` must be `eks-jobintel-eks`.
- **Namespace missing**: verify `kubectl --context eks-jobintel-eks -n jobintel get pods`.

## Rollback

Suspend CronJob:

```bash
kubectl --context "$KUBE_CONTEXT" -n "$NAMESPACE" patch cronjob jobintel-daily -p '{"spec":{"suspend":true}}'
```

Revert image (edit manifest + apply):

```bash
python scripts/k8s_render.py --overlay eks > /tmp/jobintel.yaml
rg -n "image:" /tmp/jobintel.yaml
kubectl --context "$KUBE_CONTEXT" apply -f /tmp/jobintel.yaml
```

Delete failed Jobs safely:

```bash
kubectl --context "$KUBE_CONTEXT" -n "$NAMESPACE" delete job <job_name>
```

## Rotate Secrets

Discord webhook:

```bash
kubectl --context "$KUBE_CONTEXT" -n "$NAMESPACE" delete secret jobintel-secrets
kubectl --context "$KUBE_CONTEXT" -n "$NAMESPACE" create secret generic jobintel-secrets \
  --from-literal=DISCORD_WEBHOOK_URL="<webhook>"
```

AI key (optional):

```bash
kubectl --context "$KUBE_CONTEXT" -n "$NAMESPACE" create secret generic jobintel-secrets \
  --from-literal=OPENAI_API_KEY="<key>" \
  --dry-run=client -o yaml | kubectl --context "$KUBE_CONTEXT" -n "$NAMESPACE" apply -f -
```

After secret rotation, trigger a new Job:

```bash
kubectl --context "$KUBE_CONTEXT" -n "$NAMESPACE" create job --from=cronjob/jobintel-daily jobintel-manual-$(date +%Y%m%d)
```

## Troubleshooting

S3 publish verification:

```bash
python scripts/verify_published_s3.py --bucket "$BUCKET" --run-id "<run_id>" --prefix "$PREFIX" --verify-latest
```

Common failures:
- **AccessDenied / 403**: IRSA role missing or bucket policy denies prefix.
- **ImagePullBackOff**: image not pushed or registry auth missing.
- **DNS/egress**: live scraping cannot reach host; check nodegroup egress/NAT.
- **Robots/deny-page**: logs contain `[provider_retry][robots]` and provenance shows `robots_final_allowed=false`.
- **Circuit breaker**: provenance `live_result=skipped` and `live_error_reason=circuit_breaker`.
