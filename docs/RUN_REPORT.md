# Run Report

## Location

Run reports are written to:

- `state/runs/<run_id>.json`

selection.scrape_provenance

us_only_fallback behavior (when it can happen, when it won’t)

Snapshot provenance fields (hash, mode, source)

## Schema overview

Top-level fields:

- `run_report_schema_version`: schema version string for the run report payload.
- `run_id`: run identifier (timestamp-based).
- `status`: `success`, `short_circuit`, or `error`.
- `success`: boolean success flag.
- `profiles`: list of profiles processed.
- `providers`: list of providers processed.
- `flags`: CLI flags that affected the run.
- `timestamps`: `started_at`, `ended_at`.
- `stage_durations`: per-stage timing data.
- `diff_counts`: per-profile counts of new/changed/removed.
- `content_fingerprint`: per-job stable content hash stored in ranked outputs and used for change detection.
- `inputs`: metadata for pipeline inputs (path, mtime, sha256).
- `inputs_by_provider`: per-provider input metadata (path, mtime, sha256).
- `scoring_inputs_by_profile`: selected scoring input per profile (path, mtime, sha256).
- `scoring_input_selection_by_profile`: selection details per profile, including candidates and decision rationale.
- `scoring_inputs_by_provider`: per-provider scoring input metadata by profile.
- `scoring_input_selection_by_provider`: per-provider selection details by profile.
- `outputs_by_profile`: output hashes/paths per profile.
- `outputs_by_provider`: per-provider output hashes/paths by profile.
- `git_sha`: git revision (best-effort).
- `image_tag`: image tag (if provided).
- `failed_stage`: set when `status` is `error`.

## How to replay (scoring only)

1. Verify input hashes exist in `inputs` and the files are present on disk.
2. Check `scoring_input_selection_by_profile[profile].selected` to confirm which file was used.
3. Rerun scoring with the selected input:

```bash
python scripts/score_jobs.py --profile <profile> --in_path <selected_path> \
  --out_json <ranked_json> --out_csv <ranked_csv> \
  --out_families <ranked_families> --out_md <shortlist_md>
```

4. Compare output hashes to `outputs_by_profile`.

## Common failure cases

- Missing inputs: `status=error`, `failed_stage` set, and `inputs` or `scoring_inputs_by_profile` show missing files.
- Provider/runtime failures: non-zero exit codes (`>=3`) and `failed_stage` indicates the stage.
- Validation failures: exit code `2` for missing required inputs/flags.
