# Stash 0 Nugget Triage (2026-02-13)

- Observed provider candidates in stash@{0}: airtable, canva, figma.
- Current main does not include these provider IDs in config/providers.json.
- Decision: deferred intentionally.
- Rationale: provider-platform evolution already progressed; provider additions should land in a dedicated provider PR with snapshot fixtures, schema checks, and determinism tests.
