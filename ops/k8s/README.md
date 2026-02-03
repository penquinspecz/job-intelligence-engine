# Kubernetes CronJob (JobIntel)

This directory contains a minimal, Kubernetes-native CronJob shape for running JobIntel daily.
It is intentionally plain YAML (no Helm).
The CronJob YAML uses a placeholder image name; replace it with your registry/repo tag.

## Apply (order)

```bash
kubectl apply -f ops/k8s/namespace.yaml
kubectl apply -f ops/k8s/serviceaccount.yaml
kubectl apply -f ops/k8s/role.yaml
kubectl apply -f ops/k8s/rolebinding.yaml
kubectl apply -f ops/k8s/configmap.yaml
kubectl apply -f ops/k8s/secret.example.yaml  # replace with real secret
kubectl apply -f ops/k8s/cronjob.yaml
kubectl apply -f ops/k8s/job.once.yaml  # optional: one-off Job template
```

## Run a one-off Job

Canonical one-off execution (offline-safe, deterministic):
```bash
kubectl apply -f ops/k8s/job.once.yaml
kubectl logs -n jobintel job/jobintel-once
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
- `AWS_ACCESS_KEY_ID`: AWS access key
- `AWS_SECRET_ACCESS_KEY`: AWS secret key
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
- IRSA / workload identity is supported by Kubernetes, but not assumed here.
- `role.yaml` is intentionally empty; remove Role/RoleBinding if you don’t need in-cluster RBAC.

## ConfigMap + Secret expectations

ConfigMap defaults (ops/k8s/configmap.yaml):
- Required for publish: `JOBINTEL_S3_PREFIX` (optional; defaults to `jobintel`), `JOBINTEL_AWS_REGION` (or set `AWS_REGION`).
- Deterministic defaults baked in: `CAREERS_MODE=SNAPSHOT`, `EMBED_PROVIDER=stub`, `ENRICH_MAX_WORKERS=1`.
- Publish toggles: `PUBLISH_S3` and `PUBLISH_S3_DRY_RUN` (set `PUBLISH_S3_DRY_RUN=1` for offline plan-only runs).

Secret expectations (ops/k8s/secret.example.yaml):
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

## Local smoke

Simulate the CronJob shape locally (offline, deterministic):
```bash
make cronjob-smoke
```

## Expected outputs

- Run report: `state/runs/<run_id>/run_report.json`
- Run artifacts (S3): `s3://<bucket>/<prefix>/runs/<run_id>/...`
- Latest pointers (S3): `s3://<bucket>/<prefix>/latest/<provider>/<profile>/...`

## Troubleshooting

- Permission errors: ensure the secret exists and S3 credentials are correct.
- Missing secrets: CronJob will fail on startup; check the namespace and secret name.
- Stuck or failing jobs: check `kubectl describe job` and pod logs.
- Plan/verify failures: confirm `run_report.json` exists and `verifiable_artifacts` is populated.
- If GitHub Actions are queued or flaky, rerun the workflow or wait for recovery.

## Storage notes

The CronJob uses `emptyDir` for `/app/data` and `/app/state` by default.
For persistence across runs, replace these with PVCs or a CSI-backed volume.
