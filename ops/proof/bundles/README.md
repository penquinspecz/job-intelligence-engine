# Proof Bundles (Ops Receipts)

This directory is the canonical location for proof/receipt bundles committed to the repo.

## On-Prem 72h Stability (Milestone 4)

Plan mode:
```bash
python scripts/ops/capture_onprem_stability_receipts.py --plan \
  --run-id 20260207T120000Z \
  --output-dir ops/proof/bundles \
  --namespace jobintel \
  --cluster-context k3s-pi
```

Capture one checkpoint (trial):
```bash
python scripts/ops/capture_onprem_stability_receipts.py --execute \
  --run-id 20260207T120000Z \
  --output-dir ops/proof/bundles \
  --namespace jobintel \
  --cluster-context k3s-pi \
  --checkpoint-index 0
```

72h loop:
```bash
python scripts/ops/capture_onprem_stability_receipts.py --execute --loop \
  --run-id 20260207T120000Z \
  --output-dir ops/proof/bundles \
  --namespace jobintel \
  --cluster-context k3s-pi \
  --window-hours 72 \
  --interval-minutes 360
```

After filling host evidence templates (timesync/k3s/storage), re-run:
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
