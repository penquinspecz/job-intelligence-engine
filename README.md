© 2026 Chris Menendez. Source Available — All Rights Reserved.
This repository is publicly viewable but not open source.
See LICENSE for permitted use.

# SignalCraft
Deterministic Career Intelligence for Top Technology Companies

---

## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [Roadmap](docs/ROADMAP.md)
- [Operations](docs/OPERATIONS.md)
- [Legal & Ethics](docs/LEGAL_POSITIONING.md)
- [License](LICENSE)
- [Security](SECURITY.md)

---

## Positioning

SignalCraft is a deterministic job intelligence platform for serious career operators targeting top technology companies.

- Single pane of glass across elite tech company career pages.
- Deterministic ranking with explainable scoring outputs and artifact-backed evidence.
- AI as a last-mile intelligence layer: guardrailed, cached, and reproducible.
- Infrastructure-grade execution: Kubernetes-native scheduling, replayable runs, and CI smoke contracts.

SignalCraft is not limited to AI companies. AI-focused providers are part of the platform today, but the architecture is intentionally provider-agnostic and built to expand across leading technology employers.

## What It Is Not

- Not a replacement for company career sites.
- Not a job board mirror.
- Not an uncontrolled scraper.
- Not AI hallucination-driven ranking.

## Architecture Summary

SignalCraft is architected as a product platform, not a one-off script.

- Deterministic ingestion: snapshot-first/offline-capable collection with policy-aware provider controls.
- Identity and history tracking: stable job identity, diffs, retention, and replay-ready run artifacts.
- Replayable scoring: deterministic scoring pipeline with explainable outputs and contract-tested artifacts.
- AI insights layer: weekly intelligence today, per-job intelligence roadmap, both behind strict guardrails.

Canonical pipeline entrypoint: `scripts/run_daily.py`

## Legality + Ethics

SignalCraft is designed as a discovery net:

- Always links users to original employer/source career pages.
- Does not position mirrored content as the primary experience.
- Avoids scraping arms-race behavior; policy and politeness controls are core defaults.
- Built for compliance-minded operations, with provenance, explicit failure reasons, and deterministic evidence.

See `docs/LEGAL_POSITIONING.md` for the explicit contract.

## Product Roadmap (High-Level)

- Multi-user isolation and candidate-aware run boundaries.
- Resume/profile ingestion with deterministic contracts.
- Explainability-first UI surfaces over stable backend artifacts.
- Profile-aware AI coaching with strict schema and caching guardrails.
- Alert channels beyond Discord (email/push/RSS) with deterministic behavior.
- Trust signals and transparency layers for scoring, provenance, and policy decisions.

Detailed roadmap: `docs/ROADMAP.md`

## License

SignalCraft is Source Available, not open source.

Use is governed by the SignalCraft Source Available License v1.0 in `LICENSE`.

For commercial licensing or derivative-use permissions, contact Chris Menendez in writing.
