# Dashboard Artifact Serve Hardening Receipt (2026-02-13)

## Goal
Keep dashboard artifact serving useful for normal run inspection while rejecting artifact-exfil paths fail-closed.

## Hardening Behavior
Allowed behavior:
- Serve indexed artifact files under a run directory when `index.json` maps the requested artifact name.

Rejected behavior:
- Reject invalid artifact mapping values (absolute/parent traversal) with fail-closed response.
- Reject malformed artifact names (empty/oversized/path-like) before filesystem resolution.

Compatibility behavior:
- Normal dashboard run listing/details/semantic summary and artifact fetch remain unchanged for valid requests.

## Coverage (tests)
- `test_dashboard_runs_populated`
  - proves valid indexed artifact serving still works (`200`).
- `test_dashboard_artifact_exfil_guard_rejects_invalid_mapping`
  - proves traversal-like mapping (`../secret.txt`) is rejected.
- `test_dashboard_artifact_exfil_guard_rejects_oversized_name`
  - proves malformed oversized names are rejected (`400`).
- Existing dashboard endpoint tests continue to pass, demonstrating no regression in normal reads.

## Validation Commands
```bash
kubectl kustomize ops/k8s/overlays/onprem-pi
scripts/k8s_render.py --overlay onprem-pi
make format
make lint
PYTHONPATH=src ./.venv/bin/python -m pytest -q
```

## Validation Results
- `kubectl kustomize ops/k8s/overlays/onprem-pi`: PASS (`561` lines rendered)
- `scripts/k8s_render.py --overlay onprem-pi`: PASS (`562` lines rendered)
  - local execution used `./.venv/bin/python scripts/k8s_render.py --overlay onprem-pi`
- `make format`: PASS (`396 files left unchanged`)
- `make lint`: PASS (`All checks passed!`)
- `PYTHONPATH=src ./.venv/bin/python -m pytest -q`: PASS (`526 passed, 15 skipped`)
