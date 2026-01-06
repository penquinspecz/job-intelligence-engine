# Recent Commits (last 30)
Source: `git log --oneline -n 30`

```
a0c9ee5 Centralize pipeline paths in ji_engine.config
88dd102 Remove bootstrap path hacks; add failure alerting; document editable install
08d1e42 Track scoring profiles config; default to config/profiles.json
cc0534e Use ji_engine.config in enrich_jobs; remove sys.path bootstrap
47b56b9 Use ji_engine.config in run_classify; remove sys.path bootstrap
4a6dc87 Centralize scrape paths via ji_engine.config
90a8f7b Harden daily runner: locking, failure alerts, centralized paths
cf93cd1 Harden run_daily: stale lock + failure alerts + clean control flow
bb7d40b Restore launchd wrapper script
654162e Silence urllib3 LibreSSL warning and ignore egg-info
8a7cb98 Silence urllib3 LibreSSL warning via sitecustomize
aa5f7d6 Remove PYTHONWARNINGS from launchd env
0de4c73 Tidy gitignore for generated outputs
2b4a373 Add packaging and launchd install assets
8177c94 Ignore generated job data outputs
d09f57d Stabilize daily runner: AUTO scrape fallback, env-safe launchd support, warning suppression
6324356 Make daily runner resilient + add Makefile and env template
88b0d6c Add Makefile runner + safe env template
706317c Track .env.example template
be9129c Daily pipeline: multi-profile scoring, diffing, Discord alerts
917e7e3 Daily pipeline with profile scoring, diffing, and Discord alerts
0f90e48 Add CS-prioritized job scoring with role bands, profile weights, US-only filter, and explainable outputs
200818d Enrichment via Ashby GraphQL handling and unavailable job handling
cddd309 Checkpoint: Ashby GraphQL enrichment + CS-focused classification pipeline
1a0af7e Update classifier scoring, refactor provider snapshot logic, begin RELEVANT/MAYBE pipeline
fb6d24b Add BaseJobProvider and snapshot-based OpenAI scraping (456 jobs)
70c6c5c Add BaseJobProvider, snapshot mode, and OpenAI provider refactor
10b2e7d Remove broken Mermaid diagram from README
5f6434a Fix README by re-wrapping Mermaid diagram in code fence
24a753a Fix README Mermaid parsing issue (insert newline)
```

