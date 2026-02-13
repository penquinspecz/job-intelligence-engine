# Run Report Reference

Run reports are written to `state/runs/<run_id>.json` and copied to
`state/runs/<run_id>/run_report.json`. They include metadata for reproducibility,
debugging, and audit trails. They are versioned with `run_report_schema_version`.

## Schema version
`run_report_schema_version`: integer. Current version: **1**.

## Timestamp format
All run report timestamps use UTC ISO 8601 with trailing `Z` and seconds precision
(no fractional seconds). This includes `run_id`, `timestamps.started_at`,
`timestamps.ended_at`, and any `*_at`/`*_time` fields in provenance or artifacts.

## Top-level fields
- `run_id`: ISO timestamp used to identify the run.
- `status`: status string (`success`, `short_circuit`, `error`).
- `success`: boolean derived from status.
- `failed_stage`: present when status is `error`.
- `profiles`: list of profiles processed (e.g., `["cs"]`).
- `providers`: list of providers processed (e.g., `["openai"]`).
- `flags`: CLI flags and thresholds (including `min_score`, `min_alert_score`).
- `timestamps`: `started_at`, `ended_at`.
- `stage_durations`: per-stage timings.
- `diff_counts`: per-profile diff counts (new/changed/removed).
- `provenance_by_provider`: scrape provenance (snapshot/live, hashes, parsed counts).
- `selection`: top-level selection summary including:
  - `scrape_provenance`
  - `classified_job_count`
  - `classified_job_count_by_provider`
- `inputs`: raw/labeled/enriched input file metadata (path, mtime, sha256).
- `outputs_by_profile`: ranked outputs (paths + sha256).
- Ranked job artifacts include a deterministic `job_id` per posting:
  - Preserve source `job_id` when provided.
  - Else use canonical apply/detail URL.
  - Else fall back to provider-aware deterministic identity.
- `inputs_by_provider`, `outputs_by_provider`: provider-specific input/output metadata.
- `verifiable_artifacts`: mapping of logical artifact keys to hashes:
  - Keys are `"<provider>:<profile>:<output_key>"`.
  - Values include `path` (relative to `JOBINTEL_DATA_DIR`), `sha256`, `bytes`, and `hash_algo`.
- `config_fingerprint`: sha256 of the effective, non-secret configuration inputs.
- `environment_fingerprint`: best-effort environment details (python version, platform, image tag, git sha, TZ, PYTHONHASHSEED).
- `logs`: observability pointers for this run:
  - `schema_version`, `run_id`
  - `local`: `run_dir`, `logs_dir`, `stdout`, and optional `structured_log_jsonl`
  - `k8s` (best-effort): `namespace`, optional `context`, and command templates:
    - `pod_list_command`
    - `job_list_command`
    - `logs_command_template` (grep by `JOBINTEL_RUN_ID=<run_id>`)
  - `cloud` (best-effort): AWS `region`, `cloudwatch_log_group`, `cloudwatch_log_stream` when available in env.
    - includes `cloudwatch_filter_pattern` pinned to `JOBINTEL_RUN_ID=<run_id>` for deterministic discovery.
- `log_retention`: deterministic logs-only retention summary:
  - `keep_runs`, `runs_seen`, `runs_kept`, `log_dirs_pruned`, `pruned_log_dirs`, `reason`
  - pruning only removes `state/runs/<run_id>/logs/` for older runs; it does not delete run artifacts.
- `scoring_inputs_by_profile`: selected scoring input metadata (path/mtime/sha256).
- `scoring_model`: deterministic scoring contract metadata:
  - `version` (current contract version, e.g. `v1`)
  - `algorithm_id` (stable algorithm identifier)
  - `config_sha256` (hash of normalized `config/scoring.v1.json`)
  - `module_path` + `code_sha256` (scoring implementation audit pointer)
  - `inputs` (pointer list for selected scoring input(s), profiles config, and scoring config)
- `scoring_input_selection_by_profile`: decision metadata for scoring inputs:
  - `selected_path`
  - `candidate_paths_considered` (path/mtime/sha/exists)
  - `selection_reason` (enum string)
  - `selection_reason_details` (stable reasoning object):
    - `labeled_vs_enriched` and `enriched_vs_ai` each include:
      - `rule_id` (stable string)
      - `chosen_path`
      - `candidate_paths`
      - `compared_fields` (mtimes/hashes used)
      - `decision` (short enum)
      - `decision_timestamp` (ISO 8601)
  - `comparison_details` (e.g., newer_by_seconds, prefer_ai)
  - `decision` (human-readable rule and reason)
- `archived_inputs_by_provider_profile`: archived copies of scoring dependencies:
  - `<provider>` → `<profile>` → `{selected_scoring_input, profile_config, scoring_config}`
  - Each archived entry includes `source_path`, `archived_path` (relative to `JOBINTEL_STATE_DIR`), `sha256`, `bytes`.
- `delta_summary`: delta intelligence summary if available.
- `git_sha`: best-effort git sha when available.
- `image_tag`: container image tag if set.
- `s3_bucket`, `s3_prefixes`, `uploaded_files_count`, `dashboard_url`: S3 publishing metadata (when enabled).
- Diff summary artifacts are written under the run directory (`state/runs/<run_id>/diff_summary.json` and `.md`).

### Provider provenance additions
Each provider entry in `provenance_by_provider` may include:
- `live_error_type`: one of `success`, `transient_error`, `unavailable`, `invalid_response` (when live was attempted).
- `snapshot_baseline_count`: job count from the snapshot baseline (when available).
- `failure_policy`: deterministic policy evaluation result and thresholds:
  - `decision`: `ok` or `fail`
  - `reason`: short enum-like reason string
  - `parsed_job_count`, `snapshot_baseline_count`
  - `error_rate`, `error_rate_max`, `min_jobs`, `min_snapshot_ratio`
  - `enrich_stats`: `{total, enriched, unavailable, failed}`

## Selection reason enums
Selection reasons are deterministic strings such as:
- `ai_only`
- `no_enrich_enriched_newer`
- `no_enrich_labeled_newer_or_equal`
- `no_enrich_enriched_only`
- `no_enrich_labeled_only`
- `no_enrich_missing`
- `default_enriched_required`
- `default_enriched_missing`
- `prefer_ai_enriched`

### selection_reason_details.rule_id
Rule IDs are stable strings scoped to the decision boundary:
- `labeled_vs_enriched.<decision>`
- `enriched_vs_ai.<decision>`

## How to debug a run
Use these paths to inspect artifacts:

- Run report:
  - `state/runs/<run_id>.json`
  - `state/runs/<run_id>/run_report.json`
- Run registry:
  - `state/runs/<run_id>/index.json`
- Ranked outputs:
  - `data/<provider>_ranked_jobs.<profile>.json`
  - `data/<provider>_ranked_jobs.<profile>.csv`
  - `data/<provider>_ranked_families.<profile>.json`
  - `data/<provider>_shortlist.<profile>.md`
  - `data/<provider>_top.<profile>.md`
- Alerts:
  - `data/<provider>_alerts.<profile>.json`
  - `data/<provider>_alerts.<profile>.md`
- Diff summary:
  - `state/runs/<run_id>/diff_summary.json`
  - `state/runs/<run_id>/diff_summary.md`
- AI insights (when enabled):
  - `state/runs/<run_id>/ai_insights.<profile>.json`
  - `state/runs/<run_id>/ai_insights.<profile>.md`
- AI job briefs (when enabled):
  - `state/runs/<run_id>/ai_job_briefs.<profile>.json`
  - `state/runs/<run_id>/ai_job_briefs.<profile>.md`

## Replayability
To validate reproducibility:
```bash
python scripts/replay_run.py --run-id <run_id> --profile cs
```
- Exit code `0`: reproducible
- Exit code `2`: missing inputs or mismatched hashes
- Exit code `>=3`: runtime error

To recompute scoring outputs from archived inputs and compare hashes:
```bash
python scripts/replay_run.py --run-id <run_id> --profile cs --strict --recalc
```
- Uses archived scoring inputs + profile config from the run directory (no `data/` dependency).
- If present, recalc also uses archived `scoring_config` from the run directory.
- Writes regenerated outputs under `state/runs/<run_id>/_recalc/` and compares hashes to the run report.

Machine-readable replay output:
```bash
python scripts/replay_run.py --run-id <run_id> --json
```
