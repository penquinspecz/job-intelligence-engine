© 2026 Chris Menendez. Source Available — All Rights Reserved.
This repository is publicly viewable but not open source.
See [LICENSE](LICENSE) for permitted use.

<p align="center">
  <img alt="SignalCraft" src="assets/brand/signalcraft-wordmark.light.png?raw=1#gh-light-mode-only" width="520">
  <img alt="SignalCraft" src="assets/brand/signalcraft-wordmark.dark.png?raw=1#gh-dark-mode-only" width="520">
</p>

<p align="center">
  <img alt="SignalCraft logo" src="assets/brand/signalcraft-logo.light.png?raw=1#gh-light-mode-only" width="96">
  <img alt="SignalCraft logo" src="assets/brand/signalcraft-logo.dark.png?raw=1#gh-dark-mode-only" width="96">
</p>

# SignalCraft

**Deterministic Career Intelligence for Top Technology Companies**

SignalCraft is a career intelligence engine that aggregates, normalizes, scores, and analyzes job postings directly from leading technology company career pages — with deterministic logic, reproducible outputs, and guardrailed AI augmentation.

It is built as infrastructure, not a script.

---

## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [Roadmap](docs/ROADMAP.md)
- [Operations](docs/OPERATIONS.md)
- [Legal Positioning](docs/LEGAL_POSITIONING.md)
- [License](LICENSE)
- [Security Policy](SECURITY.md)

---

## What SignalCraft Does

SignalCraft:

- Aggregates job postings directly from official company career pages
- Normalizes and de-duplicates roles across providers
- Applies deterministic scoring and ranking logic
- Tracks historical changes across runs
- Produces reproducible, artifact-backed outputs
- Optionally layers AI insights on top of stable, deterministic artifacts

The system is snapshot-first, replayable, and explainable.

Every run produces inspectable artifacts under `state/runs/<run_id>/`.

Canonical pipeline entrypoint:
`scripts/run_daily.py`

---

## Who It’s For

SignalCraft is designed for serious job seekers targeting top technology companies who want:

- A single pane of glass across elite employer career pages
- Deterministic ranking instead of opaque AI magic
- Explainable scoring outputs
- Historical tracking and change detection
- Infrastructure-grade reliability
- Guardrailed AI insights layered on top of real data

This is not a job board.
It is an intelligence layer over official sources.

---

## Core Principles

### Deterministic by Default
Same inputs → same outputs.
Every decision is logged, hashed, and replayable.

### AI Is Last-Mile
AI never replaces core logic.
AI reads structured artifacts and produces insight.
All AI outputs are cached, schema-validated, and guardrailed.

### Legality-Conscious by Design
SignalCraft:
- Links directly to original employer career pages
- Does not replace or masquerade as the source
- Respects provider policies, rate limits, and robots decisions
- Avoids scraping arms-race behavior

See [`docs/LEGAL_POSITIONING.md`](docs/LEGAL_POSITIONING.md) for the explicit design contract.

### Infrastructure-Grade Execution
- CI + Docker smoke validation
- Replayable run reports
- Snapshot debugging
- Kubernetes-native scheduling
- Object-store publishing
- Deterministic semantic augmentation

---

## High-Level Architecture

SignalCraft is built as a layered system:

1. **Ingestion Layer**  
   Config-driven provider definitions  
   Snapshot-first collection  
   Policy-aware scraping controls  

2. **Normalization + Identity Engine**  
   Stable job identity  
   URL normalization  
   Deduplication across runs  

3. **Deterministic Scoring Engine**  
   Explainable heuristics  
   Stable tie-breakers  
   Score clamping + diagnostics  

4. **History + Diff Engine**  
   Identity-based change detection  
   Run archival + replay  

5. **AI Intelligence Layer (Optional)**  
   Weekly insights  
   Structured trend analysis  
   Deterministic semantic similarity safety net  
   Cached + schema-validated outputs  

6. **Delivery Layer**  
   Dashboard API  
   Discord notifications  
   Object-store publishing  
   Kubernetes CronJobs  

Detailed architecture:
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)

---

## What It Is Not

- Not a job board mirror
- Not an uncontrolled scraper
- Not AI hallucination-driven ranking
- Not a growth-hack scraping arms race

SignalCraft is a discovery and intelligence layer — not a replacement for official employer systems.

---

## Roadmap Direction

SignalCraft is evolving toward:

- Multi-user isolation
- Resume/profile ingestion
- Profile-aware scoring
- Per-job AI recommendations
- Explainability-focused UI
- Consumer-grade user experience
- Expanded provider coverage across top technology companies
- Compliance-aware partnerships

Full roadmap:
[`docs/ROADMAP.md`](docs/ROADMAP.md)

---

## License

SignalCraft is Source Available, not open source.

Use is governed by the SignalCraft Source Available License v1.0 in [`LICENSE`](LICENSE).

Commercial use, redistribution, derivative works, and competing hosted services are prohibited without written permission.

For licensing inquiries:
Contact Chris Menendez: https://www.linkedin.com/in/chmz/
