# Kubernetes (CronJob)

## What this deploys

Minimal manifests under `ops/k8s/`:
- `CronJob` that runs `python scripts/run_daily.py --profiles cs --us_only --no_post --no_enrich` (configurable).
- `ConfigMap` for non-secret config.
- Two `PVC`s for `/app/data` and `/app/state`.

The `CronJob` uses an init container to seed `data/openai_snapshots/index.html` and `data/candidate_profile.json` into the data volume if they are missing (no network).

## Prereqs

- Build/push the image to a registry your cluster can pull, and update `ops/k8s/cronjob.yaml` `image:` values accordingly.
- Provide a secret named `jobintel-secrets` (in the same namespace) if you want optional tokens:
  - `OPENAI_API_KEY` (only needed if you run with `--ai`)
  - `DISCORD_WEBHOOK_URL` (only needed if you remove `--no_post`)

Example secret creation:

```bash
kubectl -n jobintel create secret generic jobintel-secrets \
  --from-literal=OPENAI_API_KEY='...' \
  --from-literal=DISCORD_WEBHOOK_URL='...'
```

## Apply

```bash
kubectl apply -k ops/k8s
```

Check status/logs:

```bash
kubectl -n jobintel get cronjob,job,pod
kubectl -n jobintel logs job/<job-name> -c jobintel
```

## Configuration

Default args are set in `ops/k8s/configmap.yaml` as `RUN_DAILY_ARGS`. Edit it to change profiles/flags.

Storage:
- Default uses two PVCs: `jobintel-data` and `jobintel-state`.
- If you switch either mount to `emptyDir`, outputs/history will be ephemeral and disappear when the pod exits.

## Optional: publish artifacts to S3

This is not enabled by default.

Mode A (PVC only):
- Use the CronJob as-is; artifacts stay on the PVCs.

Mode B (PVC + publish to S3):
- Run `scripts/publish_s3.py` after the daily run, using the same `/app/state` mount.
- You can do this either by:
  - adding a second container in the CronJob that runs after the main container completes, or
  - scheduling a separate `Job` that mounts the same PVC and runs `python scripts/publish_s3.py --profile cs --latest --bucket ...`.

Required env vars for publish:
- `JOBINTEL_S3_BUCKET` (or pass `--bucket`).
- Optional `JOBINTEL_S3_PREFIX`.
- AWS credentials via standard env/IRSA.

Security defaults:
- Runs as non-root.
- Drops all Linux capabilities.
- Uses `seccompProfile: RuntimeDefault`.
- Uses `readOnlyRootFilesystem: true` and mounts `/tmp`, `/app/data`, `/app/state` as writable volumes.
