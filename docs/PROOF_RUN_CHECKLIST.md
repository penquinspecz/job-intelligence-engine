# Proof Run Checklist (Milestone 2)

This checklist is for a **one-time, real in-cluster run** (Kubernetes/EKS) that proves
the pipeline runs end-to-end and publishes deterministic artifacts. It is
**copy/pasteable** and designed to produce proof artifacts for the PR.

## Prereqs
- `kubectl` context points at the target cluster (`kubectl config current-context`).
- AWS CLI configured (or assumed role) with access to ECR/EKS/S3.
- `aws sts get-caller-identity` succeeds.
- S3 bucket exists for publish targets and is reachable with your role.
- Image pushed and accessible by the cluster (no ImagePullBackOff).
- S3 bucket exists for publish targets.
- Discord webhook (optional).

Set these placeholders first (adjust as needed):

```bash
export AWS_REGION="<region>"
export CLUSTER_NAME="<eks_cluster>"
export KUBE_CONTEXT="<kube_context>"
export NAMESPACE="jobintel"
export BUCKET="<s3_bucket>"
export PREFIX="jobintel"
```

## 1) Apply manifests

```bash
python scripts/k8s_render.py --overlay aws-eks > /tmp/jobintel.yaml
kubectl --context "$KUBE_CONTEXT" apply -f /tmp/jobintel.yaml
```

## 2) Run a one-off Job

```bash
kubectl --context "$KUBE_CONTEXT" -n "$NAMESPACE" \
  create job --from=cronjob/jobintel-daily jobintel-manual-$(date +%Y%m%d)
```

## 3) Fetch logs

```bash
kubectl --context "$KUBE_CONTEXT" -n "$NAMESPACE" \
  logs -f job/jobintel-manual-$(date +%Y%m%d)
```

## 4) Capture receipts (live proof)

This writes local proof artifacts and enforces live provenance checks.

```bash
NS="$NAMESPACE" bash scripts/prove_live_scrape_eks.sh
```

Verify S3 publish for the captured run_id (from the script output):

```bash
python scripts/verify_published_s3.py --bucket "$BUCKET" --run-id "<run_id>" --prefix "$PREFIX" --verify-latest
```

## Expected outputs (proof artifacts)
- A log line containing `JOBINTEL_RUN_ID=<run_id>`.
- A proof JSON file at `state/proofs/<run_id>.json`.
- A proof log file at `ops/proof/liveproof-<run_id>.log` containing `JOBINTEL_RUN_ID` and `[run_scrape][provenance]`.
- `verify_published_s3` output with `"ok": true`.
- S3 keys under:
  - `runs/<run_id>/<provider>/<profile>/...`
  - `latest/<provider>/<profile>/...`

## Common failure modes

- `AccessDenied` from S3: IRSA role missing or bucket policy denies prefix.
- `ImagePullBackOff`: image not pushed or registry auth missing.
- `CrashLoopBackOff`: missing required env/secret keys.
- `verify_published_s3 failed`: run_id incorrect or publish disabled.

## Proof snippet (local extraction)

Use the local extractor against the run report and plan JSON:

```bash
python scripts/proof_run_extract.py \
  --run-report /path/to/run_report.json \
  --plan-json /path/to/publish_plan.json
```
