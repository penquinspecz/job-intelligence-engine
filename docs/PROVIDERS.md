# Provider Authoring

SignalCraft provider additions must stay snapshot-first, deterministic, and offline-reproducible in tests.

## Enablement Contract

Provider enablement is explicit and guarded. Use the contract checks before toggling `enabled=true`.

Validate one provider:

```bash
make provider-validate provider=<provider_id>
```

Attempt enable (dry-run; no config edits):

```bash
make provider-enable provider=<provider_id> WHY="why this provider should be enabled now"
```

Apply enablement after checks are green:

```bash
make provider-enable provider=<provider_id> WHY="why this provider should be enabled now" I_MEAN_IT=1
```

`enable` refuses when any of these are true:
- `careers_urls` missing/empty
- `allowed_domains` missing/empty
- `extraction_mode` missing/invalid
- snapshot provider fixture missing
- snapshot manifest missing entry or hash/bytes mismatch

Guardrail: no config mutation happens unless `--i-mean-it` (or `I_MEAN_IT=1`) is supplied.

## Snapshot Baseline Updates

Use `update-snapshot-manifest` only when a provider snapshot fixture was intentionally changed.

```bash
PYTHONPATH=src .venv/bin/python scripts/provider_authoring.py update-snapshot-manifest --provider <provider_id>
```

Equivalent make target:

```bash
make provider-manifest-update provider=<provider_id>
```

What this command does:
- Loads `config/providers.json` and resolves exactly one provider.
- Reads that provider's configured `snapshot_path`.
- Computes pinned `bytes` and `sha256` for that file.
- Updates only that provider's key in `tests/fixtures/golden/snapshot_bytes.manifest.json`.

What this command does not do:
- It does not fetch from network.
- It does not auto-enable providers.
- It does not rewrite other providers' manifest entries.

## When You Must Run `update-snapshot-manifest`

Run it when all of these are true:
- You intentionally changed bytes in `data/<provider>_snapshots/...`.
- The provider remains snapshot-backed for deterministic runs.
- You want CI immutability checks to pin the new baseline.

Do not run it for unrelated code-only changes.

## CI Failure Remediation

If CI fails with snapshot contract errors (for example missing fixture/manifest mismatch):

1. Run `make provider-validate provider=<provider_id>` to see the failing check.
2. If fixture bytes changed intentionally, run `make provider-manifest-update provider=<provider_id>`.
3. Re-run `make gate` locally.
4. Keep providers disabled until validation + gate pass.

## PR Hygiene Note

If `config/providers.json` changes in a PR, include one explicit line in the PR body:
- `snapshot manifest update required: yes` or
- `snapshot manifest update required: no`

If `yes`, include the exact command used and provider id(s).
