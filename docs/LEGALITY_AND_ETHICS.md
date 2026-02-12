# Legality and Ethics Guardrails

This document describes SignalCraft engineering guardrails for lawful, responsible operation.
It is not legal advice.

## Product Intent

SignalCraft is a discovery-and-alert layer for jobs.
It is not intended to replace employer career sites as the system of record.

## Non-Negotiable Rules

- Always provide canonical outbound links to original employer/source job pages.
- Keep UI/alerts focused on signals, summaries, and diffs instead of mirroring full source content.
- Treat any raw job text used for pipeline/replay as internal artifact data with hygiene controls.
- Respect robots directives and site policy decisions configured in the provider layer.
- Enforce politeness controls (rate limits, concurrency caps, backoff, jitter, circuit breaker).
- Do not implement credentialed scraping, anti-bot bypassing, or paywall circumvention in core scope.

## User-Agent and Attribution Stance

- Use an explicit, stable user-agent string that identifies the project.
- Keep repository/contact metadata in the user-agent payload.
- Preserve provenance records so policy/scrape decisions are auditable.

## Operational Expectations

- Provider policy decisions should be explicit in provenance (not silent).
- Unavailability/failure reasons should remain visible and deterministic.
- If a provider must be disabled for policy reasons, disable it explicitly in config.

## User Responsibility Reminder

SignalCraft outputs are decision support.
Users should verify details and submit applications on the source employer site.
