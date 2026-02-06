# Kubernetes CronJob (JobIntel)

This directory contains a minimal, Kubernetes-native CronJob shape for running JobIntel daily.
It is intentionally plain YAML + kustomize (no Helm).
The CronJob YAML uses a placeholder image name; replace it with your registry/repo tag.

Runbook: `ops/k8s/RUNBOOK.md` (deploy, inspect, rollback, rotate secrets).

## Runtime contract

Required env vars (names only):
- `JOBINTEL_S3_BUCKET` (only when publishing)
- `AWS_REGION` or `JOBINTEL_AWS_REGION` (when publishing to AWS)

Optional env vars:
- `CAREERS_MODE` (`SNAPSHOT` default; set `LIVE` for live mode)
- `EMBED_PROVIDER` (default `stub`)
- `ENRICH_MAX_WORKERS` (default `1`)
- `AI_ENABLED` (default `0`)
- `PUBLISH_S3` / `PUBLISH_S3_DRY_RUN`
- `JOBINTEL_S3_PREFIX` (default `jobintel`)
- `DISCORD_WEBHOOK_URL`, `OPENAI_API_KEY`

Storage expectations:
- Local scratch: `emptyDir` for `/tmp` and `/work`.
- Local run data: `emptyDir` for `/app/data` and `/app/state` (swap for PVCs if you want persistence).
- Persistent artifacts: object-store publish via `publish_s3` (`S3` compatible).

Container command:
- `python scripts/run_daily.py --profiles cs --us_only --no_post --snapshot-only --offline`

Deterministic defaults:
- `CAREERS_MODE=SNAPSHOT`
- `ENRICH_MAX_WORKERS=1`
- `AI_ENABLED=0`

Live mode requires explicit provider policy env vars:
- `JOBINTEL_PROVIDER_ERROR_RATE_MAX`
- `JOBINTEL_PROVIDER_MIN_JOBS`
- `JOBINTEL_PROVIDER_MIN_SNAPSHOT_RATIO`
- `JOBINTEL_PROVIDER_MAX_ATTEMPTS`
- `JOBINTEL_PROVIDER_BACKOFF_BASE`
- `JOBINTEL_PROVIDER_BACKOFF_MAX`

## Kustomize packages

Base (portable):
- `ops/k8s/jobintel/`

AWS EKS overlay (IRSA + publish toggles):
- `ops/k8s/overlays/aws-eks/`

Live overlay (opt-in):
- `ops/k8s/overlays/live/`

IRSA note (conceptual):
- IRSA maps a Kubernetes ServiceAccount to a cloud IAM role so pods can access object stores without static keys.
- The AWS overlay expects `JOBINTEL_IRSA_ROLE_ARN` at render time (no manual YAML edits).

## Apply (order)

```bash
kubectl apply -k ops/k8s/jobintel
```

For EKS with IRSA:
```bash
export JOBINTEL_IMAGE=<account>.dkr.ecr.<region>.amazonaws.com/jobintel:<tag-or-digest>
JOBINTEL_IRSA_ROLE_ARN=arn:aws:iam::<account>:role/<role> \
  JOBINTEL_IMAGE="$JOBINTEL_IMAGE" \
  python scripts/k8s_render.py --overlay aws-eks --image "$JOBINTEL_IMAGE" > /tmp/jobintel.yaml
kubectl apply -f /tmp/jobintel.yaml
```

Full AWS flow (ECR push + preflight + render/apply): `ops/aws/EKS_ECR_GOLDEN_PATH.md`.

Preflight (offline, no AWS calls):
```bash
make preflight
```

## Mode matrix

SNAPSHOT (default, deterministic):
- Args include `--snapshot-only --offline`
- `CAREERS_MODE=SNAPSHOT`
- Safe for scheduled daily runs

LIVE (opt-in, provider-dependent):
- Args remove `--snapshot-only --offline`
- `CAREERS_MODE=LIVE`
- Requires explicit provider policy env vars (see above)

Publish (object store):
- `PUBLISH_S3=1` and `PUBLISH_S3_DRY_RUN=0`
- Use `aws-eks` overlay to enable publish

## Run a one-off Job

Canonical one-off execution (offline-safe, deterministic):
```bash
kubectl apply -k ops/k8s/jobintel
kubectl delete job -n jobintel jobintel-manual --ignore-not-found
kubectl create job -n jobintel --from=cronjob/jobintel-daily jobintel-manual
kubectl logs -n jobintel job/jobintel-manual
```

You can print the full run-once command sequence locally:
```bash
make k8s-run-once
```

Alternative: use the CronJob template to run a single execution:
```bash
kubectl create job -n jobintel --from=cronjob/jobintel-daily jobintel-run-once
kubectl logs -n jobintel job/jobintel-run-once
```

## Required secrets

Create a secret named `jobintel-secrets` with the following keys (use only what you need):
- `JOBINTEL_S3_BUCKET`: target bucket for publish
- `AWS_ACCESS_KEY_ID`: AWS access key (only if not using IRSA)
- `AWS_SECRET_ACCESS_KEY`: AWS secret key (only if not using IRSA)
- `DISCORD_WEBHOOK_URL`: optional alerts
- `OPENAI_API_KEY`: optional AI features

Example:
```bash
kubectl -n jobintel create secret generic jobintel-secrets \
  --from-literal=JOBINTEL_S3_BUCKET=your-bucket \
  --from-literal=AWS_ACCESS_KEY_ID=... \
  --from-literal=AWS_SECRET_ACCESS_KEY=... \
  --from-literal=DISCORD_WEBHOOK_URL=... \
  --from-literal=OPENAI_API_KEY=...
```

Notes:
- Secrets-based auth is the primary example.
- IRSA / workload identity is supported and preferred for EKS runs.
- `role.yaml` is intentionally empty; remove Role/RoleBinding if you don’t need in-cluster RBAC.

## ConfigMap + Secret expectations

ConfigMap defaults (ops/k8s/jobintel/configmap.yaml):
- Required for publish: `JOBINTEL_S3_PREFIX` (optional; defaults to `jobintel`), `JOBINTEL_AWS_REGION` (or set `AWS_REGION`).
- Deterministic defaults baked in: `CAREERS_MODE=SNAPSHOT`, `EMBED_PROVIDER=stub`, `ENRICH_MAX_WORKERS=1`.
- Publish toggles: `PUBLISH_S3` and `PUBLISH_S3_DRY_RUN` (set `PUBLISH_S3_DRY_RUN=1` for offline plan-only runs).

Secret expectations (ops/k8s/jobintel/secret.example.yaml):
- Required to actually publish: `JOBINTEL_S3_BUCKET` + AWS credentials (or IRSA/workload identity instead).
- Optional: `DISCORD_WEBHOOK_URL`, `OPENAI_API_KEY`.

## Dry-run / deterministic mode

To run without AWS calls:
- Set `PUBLISH_S3_DRY_RUN=1` (or `PUBLISH_S3=0`) in the ConfigMap or at runtime.
- CronJob args already include `--snapshot-only` for offline determinism.

Example override:
```bash
kubectl set env cronjob/jobintel-daily -n jobintel PUBLISH_S3_DRY_RUN=1
```

To override any env var without editing YAML:
```bash
kubectl set env cronjob/jobintel-daily -n jobintel JOBINTEL_S3_PREFIX=jobintel-dev
```

## Verification

Generate a publish plan (offline, no AWS calls):
```bash
python scripts/publish_s3.py --run-id <run_id> --plan --json > /tmp/jobintel_plan.json
```

Verify the plan offline (no AWS calls):
```bash
python scripts/verify_published_s3.py --offline --plan-json /tmp/jobintel_plan.json
```

After a real publish, verify S3 objects (requires credentials):
```bash
python scripts/verify_published_s3.py \
  --bucket "$JOBINTEL_S3_BUCKET" \
  --run-id <run_id> \
  --verify-latest
```

Run replay smoke locally against a run report:
```bash
python scripts/replay_run.py --run-id <run_id> --strict
```

## AWS/EKS hosting runbook (one-off proof run)

Set kube context (example):
```bash
kubectl config use-context <your-eks-context>
```

EKS bootstrap (Terraform -> kubeconfig -> proof run):
- See `ops/aws/infra/eks/README.md` for required variables and apply steps.

Then set the ServiceAccount IRSA annotation using the Terraform output:
```bash
JOBINTEL_IRSA_ROLE_ARN="$(terraform -chdir=ops/aws/infra/eks output -raw jobintel_irsa_role_arn)"
```

Create secrets (no secrets committed):
```bash
kubectl -n jobintel create secret generic jobintel-secrets \
  --from-literal=JOBINTEL_S3_BUCKET=your-bucket \
  --from-literal=AWS_ACCESS_KEY_ID=... \
  --from-literal=AWS_SECRET_ACCESS_KEY=... \
  --from-literal=DISCORD_WEBHOOK_URL=... \
  --from-literal=OPENAI_API_KEY=...
```

IAM permissions (IRSA):
- Use IRSA to map the ServiceAccount to an IAM role with the actions documented in `ops/aws/README.md`.
- The AWS overlay adds the ServiceAccount annotation placeholder; replace it with your IAM role ARN.

Apply base + AWS overlay:
```bash
JOBINTEL_IRSA_ROLE_ARN="$JOBINTEL_IRSA_ROLE_ARN" \
  python scripts/k8s_render.py --overlay aws-eks > /tmp/jobintel.yaml
kubectl apply -f /tmp/jobintel.yaml
```

Apply base + LIVE overlay:
```bash
kubectl apply -k ops/k8s/overlays/live
```

Run a one-off Job from the CronJob template:
```bash
kubectl delete job -n jobintel jobintel-manual-$(date +%Y%m%d) --ignore-not-found
kubectl create job -n jobintel --from=cronjob/jobintel-daily jobintel-manual-$(date +%Y%m%d)
kubectl logs -n jobintel job/jobintel-manual-$(date +%Y%m%d)
```

Capture proof (extracts run_id from logs if omitted):
```bash
python scripts/prove_cloud_run.py \
  --bucket "$JOBINTEL_S3_BUCKET" \
  --prefix "$JOBINTEL_S3_PREFIX" \
  --namespace jobintel \
  --job-name jobintel-manual-$(date +%Y%m%d) \
  --kube-context <your-eks-context>
```

## EKS proof run - copy/paste commands

Publish-enabled, snapshot-only proof run (real S3, no dry-run):
```bash
export JOBINTEL_S3_BUCKET=<bucket>
python scripts/preflight_env.py --mode publish

export JOBINTEL_IRSA_ROLE_ARN="$(terraform -chdir=ops/aws/infra/eks output -raw jobintel_irsa_role_arn)"
python scripts/k8s_render.py --overlay aws-eks > /tmp/jobintel.yaml
kubectl apply -f /tmp/jobintel.yaml

kubectl -n jobintel create secret generic jobintel-secrets \
  --from-literal=JOBINTEL_S3_BUCKET="$JOBINTEL_S3_BUCKET" \
  --from-literal=DISCORD_WEBHOOK_URL=... \
  --from-literal=OPENAI_API_KEY=...

kubectl -n jobintel create job --from=cronjob/jobintel-daily jobintel-manual-<yyyymmdd>
kubectl -n jobintel logs -f job/jobintel-manual-<yyyymmdd>

python scripts/prove_cloud_run.py \
  --bucket <bucket> \
  --prefix jobintel \
  --namespace jobintel \
  --job-name jobintel-manual-<yyyymmdd> \
  --kube-context <context>

python scripts/verify_published_s3.py \
  --bucket <bucket> \
  --run-id <run_id> \
  --verify-latest
```

Live + publish (opt-in, provider-dependent):
```bash
python scripts/k8s_render.py --overlay live --overlay aws-eks > /tmp/jobintel-live.yaml
kubectl apply -f /tmp/jobintel-live.yaml
```

Notes:
- Run the secret command once; use `kubectl set env` or secret updates to change values.
- The AWS overlay enables `PUBLISH_S3=1` and `PUBLISH_S3_DRY_RUN=0` with a bucket placeholder.

## Local smoke

Simulate the CronJob shape locally (offline, deterministic):
```bash
make cronjob-smoke
```

## Expected outputs

- Run report: `state/runs/<run_id>/run_report.json`
- Run artifacts (S3): `s3://<bucket>/<prefix>/runs/<run_id>/<provider>/<profile>/...`
- Latest pointers (S3): `s3://<bucket>/<prefix>/latest/<provider>/<profile>/...`

## Retention guidance

- Local state: keep the last N runs (for example 30) if using PVCs; prune out-of-band.
- Object store: apply a lifecycle policy to expire `runs/<run_id>/` after N days; keep `latest/` and `state/` keys indefinitely.

## Troubleshooting

- Permission errors: ensure the secret exists and S3 credentials are correct.
- Missing secrets: CronJob will fail on startup; check the namespace and secret name.
- Stuck or failing jobs: check `kubectl describe job` and pod logs.
- Plan/verify failures: confirm `run_report.json` exists and `verifiable_artifacts` is populated.
- If GitHub Actions are queued or flaky, rerun the workflow or wait for recovery.

## Storage notes

The CronJob uses `emptyDir` for `/app/data` and `/app/state` by default.
For persistence across runs, replace these with PVCs or a CSI-backed volume.
