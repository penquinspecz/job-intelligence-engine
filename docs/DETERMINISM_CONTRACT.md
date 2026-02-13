# Determinism Contract

## 1) What “deterministic” means in this repo

Deterministic means **byte-identical outputs given the same inputs**. That includes:
- Stable ordering of lists and keys before serialization.
- Canonical JSON/CSV output formatting.
- Fixed execution environment where relevant (Docker no-cache is the source of truth).

If the inputs (snapshots, config, profile) are unchanged, the ranked outputs and run report hashes must be identical.

## 2) Snapshot immutability rule

Pinned snapshots under `data/*_snapshots/` are **immutable fixtures**. Tests and runs must not mutate them.

Guardrails:
- Pre-commit hook blocks snapshot commits unless explicitly allowed.
- Snapshot immutability verifier fails if bytes drift.

Override workflow (intentional refresh only):
- Set `ALLOW_SNAPSHOT_CHANGES=1` when committing a snapshot refresh.
- Update the snapshot bytes manifest to reflect new pinned bytes.

Why: snapshot drift makes “local green / Docker red” failures, and breaks golden reproducibility.

## 3) Run report + replay verification

Run reports capture inputs/outputs and their hashes. Replay verification re-computes hashes and compares.

Scoring Determinism Contract v1:
- Scoring uses strict, versioned config at `config/scoring.v1.json`.
- Every run report records `scoring_model`:
  - `version`, `algorithm_id`
  - `config_sha256` (normalized hash)
  - `module_path`, `code_sha256`
  - `inputs` pointer list (selected scoring input + profiles config + scoring config)
- Recalc replay uses archived scoring dependencies under:
  - `state/runs/<run_id>/inputs/<provider>/<profile>/selected_scoring_input.json`
  - `state/runs/<run_id>/inputs/<provider>/<profile>/profiles.json`
  - `state/runs/<run_id>/inputs/<provider>/<profile>/scoring.v1.json` (when present)

Breaking scoring changes policy:
- Any scoring semantic change (rules, multipliers, blend behavior, config values) must bump scoring contract version.
- If code/config drift occurs without version bump, drift tests fail.
- To bump safely:
  1) Add new versioned scoring config (for example `config/scoring.v2.json`)
  2) Update contract metadata version/algorithm id
  3) Refresh golden replay fixtures and drift signature intentionally
  4) Document expected scoring semantic deltas in the PR

Command:
```bash
python scripts/replay_run.py --run-id <run_id> --strict
```

Exit codes:
- `0` success (all hashes match)
- `2` missing artifacts or mismatches
- `>=3` runtime errors

Replay never regenerates artifacts. It only verifies recorded hashes.

## 4) Diff artifacts + diff-only alerts

Each run writes deterministic diff artifacts per provider/profile:
- `<provider>_diff.<profile>.json` (added/changed/removed lists, sorted by identity)
- `<provider>_diff.<profile>.md` (short human summary)

Identity normalization rules:
- `job_id` is casefolded and whitespace-normalized.
- URLs drop tracking parameters (`utm_*`, `gh_*`, `lever_*`, `ref`, `source`) and fragments.
- URL scheme/host are lowercased; paths are stripped of trailing `/`.

Changed fields (stable only):
- `title`, `location`, `team/department`, normalized `apply_url`
- `score_bucket` (5-point buckets when score is present)

Diff reports include a deterministic `summary_hash` for CI comparisons.

Previous-run selection rule (deterministic, offline-safe):
1) local `state/<provider>/<profile>/last_success.json` pointer if present
2) local `state/last_success.json` pointer if present
3) most recent local run metadata under `state/runs/`
4) S3 `state/<provider>/<profile>/last_success.json` (if enabled)

Discord notify mode is deterministic and defaults to **diff-only**:
- `DISCORD_NOTIFY_MODE=diff` (default): post only when diffs exist
- `DISCORD_NOTIFY_MODE=always`: always post summaries

## 5) S3 publish verification contract

Publish verification asserts that objects exist for each verifiable artifact recorded in the run report.

Command:
```bash
python scripts/verify_published_s3.py --bucket <bucket> --run-id <run_id> --verify-latest
```

Exit codes:
- `0` success
- `2` missing objects or validation failure
- `>=3` runtime errors

## 6) Gates

Local fast gate:
```bash
make gate-fast
```

Docker truth gate:
```bash
docker build --no-cache --build-arg RUN_TESTS=1 -t jobintel:tests .
```

## 7) Kubernetes runbook

For in-cluster execution (CronJob shape, secrets, one-off Job runs, and offline publish plan/replay steps),
see `ops/k8s/README.md`.

## 8) CI Contract Checks
The CI gate runs deterministic, offline-safe contract checks in addition to tests:
```bash
export JOBINTEL_DATA_DIR=/tmp/jobintel_ci_data
export JOBINTEL_STATE_DIR=/tmp/jobintel_ci_state
python - <<'PY'
from pathlib import Path
import json
from ji_engine.utils.verification import compute_sha256_file
data_dir = Path("/tmp/jobintel_ci_data")
state_dir = Path("/tmp/jobintel_ci_state")
data_dir.mkdir(parents=True, exist_ok=True)
run_dir = state_dir / "runs" / "ci-run"
run_dir.mkdir(parents=True, exist_ok=True)
ranked = data_dir / "openai_ranked_jobs.cs.json"
ranked.write_text("[]", encoding="utf-8")
report = {
    "run_id": "ci-run",
    "run_report_schema_version": 1,
    "verifiable_artifacts": {
        "openai:cs:ranked_json": {
            "path": ranked.name,
            "sha256": compute_sha256_file(ranked),
            "bytes": ranked.stat().st_size,
            "hash_algo": "sha256",
        }
    },
}
(run_dir / "run_report.json").write_text(json.dumps(report), encoding="utf-8")
PY
python scripts/publish_s3.py --run-dir /tmp/jobintel_ci_state/runs/ci-run --plan --json
python scripts/replay_run.py --run-dir /tmp/jobintel_ci_state/runs/ci-run --profile cs --strict --json
```
- `publish_s3 --plan --json` must emit a deterministic plan based only on `verifiable_artifacts`.
- `replay_run --strict --json` must verify hashes against the run report without regeneration.

## 9) Common failure modes + fixes (top 5)

1) **Snapshot bytes drift**
   - Symptom: immutability check fails or Docker/local mismatch.
   - Fix: restore snapshots to HEAD; refresh only with explicit workflow.

2) **Live scraping in golden tests**
   - Symptom: “Scraped N jobs” count changes or hash mismatch.
   - Fix: enforce `CAREERS_MODE=SNAPSHOT` and `--offline` in tests.

3) **Ordering nondeterminism**
   - Symptom: same data, different hash; CSV/JSON changes.
   - Fix: sort lists and keys before serialization.

4) **Environment drift (locale/time)**
   - Symptom: Docker vs local mismatch with same inputs.
   - Fix: use Docker no-cache; keep `TZ=UTC` and `PYTHONHASHSEED=0`.

5) **Golden manifest mismatch**
   - Symptom: golden hash mismatch after deterministic change.
   - Fix: update golden fixtures only after confirming snapshot-only mode.

## 10) CI vs local parity notes

- Docker no-cache build is the source of truth.
- Local fast gate is for quick feedback; it must match Docker behavior.
- If CI is flaky, rerun the workflow or wait for GitHub Actions recovery.
