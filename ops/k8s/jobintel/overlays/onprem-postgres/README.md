# Optional On-Prem Postgres Overlay

This overlay extends `overlays/onprem` with a single-node Postgres StatefulSet.

Apply:

```bash
kubectl apply -k ops/k8s/jobintel/overlays/onprem-postgres
```

Notes:
- This is optional. Default on-prem contract uses filesystem-backed state artifacts.
- Create `jobintel-postgres-secrets` out-of-band from `postgres-secret.example.yaml`.
- Do not commit real DB credentials.
