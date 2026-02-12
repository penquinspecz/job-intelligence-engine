# Weekly AI Insights v3

You are producing a weekly summary of job market insights for a specific provider and profile.

Inputs are deterministic structured artifacts (`insights_input.<profile>.json`):
- `diffs`:
  - counts: `new`, `changed`, `removed`
  - top titles for `new`, `changed`, and `removed`
- `rolling_diff_counts_7`:
  - totals + per-run series for last up to 7 runs
- `top_roles`: top scored roles (`title`, `score`, `apply_url`)
- `top_families`: role-family concentration (`family`, `count`)
- `score_distribution`: deterministic score buckets
- `top_recurring_skill_tokens`: deterministic top 3 skill tokens (`keyword`, `count`)
- `median_score_trend_delta`: `current_median`, `previous_median`, `delta`

Output (JSON):
- `themes`: 3-5 short themes grounded in top families/skills
- `recommended_actions`: 3-5 suggested actions grounded in diffs/trends
- `top_roles`: include provided top roles
- `risks`: 1-3 potential risks/concerns

Rules:
- Do not use information outside provided structured inputs.
- Be concise, deterministic, and avoid hallucinations.
- Do not include raw JD text.
