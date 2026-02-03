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

After a run, verify published artifacts (requires credentials):
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

- Run report: `state/runs/<run_id>.json`
- Run artifacts (S3): `s3://<bucket>/<prefix>/runs/<run_id>/...`
- Latest pointers (S3): `s3://<bucket>/<prefix>/latest/<provider>/<profile>/...`

## Troubleshooting

- Permission errors: ensure the secret exists and S3 credentials are correct.
- Missing secrets: CronJob will fail on startup; check the namespace and secret name.
- Stuck or failing jobs: check `kubectl describe job` and pod logs.
- If GitHub Actions are queued or flaky, rerun the workflow or wait for recovery.

## Storage notes

The CronJob uses `emptyDir` for `/app/data` and `/app/state` by default.
For persistence across runs, replace these with PVCs or a CSI-backed volume.
