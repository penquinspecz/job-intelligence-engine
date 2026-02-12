# Release Process (CLI-first)

This is the canonical lightweight process for SignalCraft releases.

## Versioning policy

- We use SemVer (`MAJOR.MINOR.PATCH`).
- Pre-1.0 rule: breaking changes are allowed, but still require explicit changelog notes and deterministic validation.

## Release checklist

1. Sync and verify `main` is clean.
2. Run full hygiene locally.
3. Update `CHANGELOG.md` (`[Unreleased]` and new version section).
4. Ensure version source of truth is set correctly (currently `pyproject.toml`).
5. Commit release prep and merge to `main`.
6. Create and push the annotated git tag.
7. Create GitHub release notes from the tag.

## Copy/paste commands

```bash
git fetch origin
git checkout main
git reset --hard origin/main
git status -sb

make format
make lint
AWS_CONFIG_FILE=/dev/null AWS_SHARED_CREDENTIALS_FILE=/dev/null AWS_EC2_METADATA_DISABLED=true PYTHONPATH=src ./.venv/bin/python -m pytest -q
```

```bash
# Example for v0.1.0
git tag -a v0.1.0 -m "SignalCraft v0.1.0: Deterministic Core + Guardrailed AI Foundation"
git push origin v0.1.0
gh release create v0.1.0 --generate-notes --title "v0.1.0"
```

## Notes

- Do not tag from a dirty worktree.
- Do not skip the AWS-isolated pytest gate.
- Keep release notes artifact-grounded (receipts/tests), not aspirational.
