# On-Prem Ops Hardening Receipt (2026-02-13)

## Scope
Ops-only hardening for on-prem exposure posture:
- `ops/k8s/overlays/onprem-pi/*`
- `ops/onprem/RUNBOOK_DEPLOY.md`
- `SECURITY.md`

This receipt intentionally excludes dashboard API code changes so ops hardening can be reviewed and merged independently.

## Controls Covered
- Ingress security annotations and middleware chain
- Baseline dashboard NetworkPolicy for ingress isolation
- Cloud-agnostic exposure guidance (Cloudflare Tunnel preferred, strict port-forward fallback)
- Explicit separation of ops controls from application-level artifact-serving controls

## Validation Commands
```bash
kubectl kustomize ops/k8s/overlays/onprem-pi
scripts/k8s_render.py --overlay onprem-pi
make format
make lint
PYTHONPATH=src ./.venv/bin/python -m pytest -q
```

## Validation Results
- `kubectl kustomize ops/k8s/overlays/onprem-pi`: PASS (`561` rendered lines)
- `scripts/k8s_render.py --overlay onprem-pi`: PASS (`562` rendered lines)
  - local execution note: script file is not executable in this checkout, so validation used
    `./.venv/bin/python scripts/k8s_render.py --overlay onprem-pi`.
- `make format`: PASS (`396 files left unchanged`)
- `make lint`: PASS (`All checks passed!`)
- `PYTHONPATH=src ./.venv/bin/python -m pytest -q`: PASS (`526 passed, 15 skipped`)

## Compatibility Notes
- No AWS-specific assumptions were introduced.
- Manifests remain declarative and k8s-native.
- No runtime pipeline behavior/scoring semantics changed.
