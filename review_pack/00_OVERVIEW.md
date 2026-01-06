# Overview

What this project does:
- Scrapes OpenAI careers, classifies job relevance, enriches via Ashby GraphQL + HTML fallback, scores against profiles, and emits ranked/shortlist outputs (optionally alerts to Discord).

Main pipeline stages:
- Scrape → Classify → Enrich → Score → Diff/Alert (or offline golden-master tests).

Key entrypoints/commands:
- Full daily run: `python scripts/run_daily.py --profiles cs,tam,se --us_only --no_post`
- Stage runners: `python scripts/run_scrape.py --mode AUTO`, `python scripts/run_classify.py`, `python -m scripts.enrich_jobs`, `python scripts/score_jobs.py --profile cs`
- Tests: `pytest -q`
- Editable install: `pip install -e .`

Notes:
- Paths are centralized in `src/ji_engine/config.py`.
- Logging is structured (timestamp/level) and configured in `run_daily.py` (other scripts self-configure if run directly).

