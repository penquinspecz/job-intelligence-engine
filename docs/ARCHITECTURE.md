© 2026 Chris Menendez. Source Available — All Rights Reserved.
This repository is publicly viewable but not open source.
See LICENSE for permitted use.

# Architecture

SignalCraft is architected as a deterministic career intelligence engine — not a scraping script, not an AI toy, and not a job board clone.

The system is designed so that every run is:

- Reproducible
- Explainable
- Operationally inspectable
- Legally defensible
- Evolvable into a multi-user product

Primary pipeline entrypoint: `scripts/run_daily.py`

---

# System Philosophy

SignalCraft follows a strict architectural rule:

> Deterministic Core. AI as Sidecar. Artifacts as Source of Truth.

The deterministic core owns ingestion, normalization, identity, scoring, and diffing.

AI layers may enhance interpretation — but they never replace core artifacts.

This separation is the foundation of product trust.

---

# Product Output Contract

Each run produces a complete forensic artifact tree under: state/runs/<run_id>/

Artifacts include:

- Canonical normalized job records
- Stable identity fingerprints
- Deterministic ranking outputs
- Diff classification (new / changed / removed)
- Run report + provenance
- Optional semantic summary
- Optional AI insights
- Cost accounting

If AI fails, the core still works.

If semantic logic changes, artifacts remain replayable.

If models change, structured input hashes invalidate caches deterministically.

This makes SignalCraft an *engineering-grade intelligence engine*, not a probabilistic black box.

---

# Layered Architecture

## 1. Ingestion Layer (Config-Driven Providers)

- Provider registry defines provider behavior.
- Snapshot and live modes are policy-aware.
- Contracts are enforced fail-closed.
- Robots.txt and compliance posture respected by design.
- Provenance metadata captured per provider.

Providers are configuration-driven where possible to reduce surface area.

---

## 2. Deterministic Normalization

- Canonical structures enforced.
- Stable field ordering.
- Versioned normalization contracts (`semantic_norm_v1`, etc).
- Replay-safe transforms.

Normalization ensures downstream logic operates on stable data, not raw HTML variance.

---

## 3. Identity Engine

Each job receives a stable identity signal.

Identity supports:

- Deduplication
- Run-over-run comparison
- Stable diff classification
- Deterministic tie-breaking

Identity is a core moat layer — it enables temporal intelligence rather than snapshot scraping.

---

## 4. Scoring Engine

Base scoring is:

- Deterministic
- Explainable
- Replayable

Semantic/AI influence:

- Is bounded
- Is optional
- Is policy-controlled
- Cannot unilaterally override deterministic ranking without explicit configuration

This preserves trust while allowing intelligence augmentation.

---

## 5. History + Diff Engine

SignalCraft is temporal.

Each run compares against historical artifacts.

The diff engine classifies:

- New jobs
- Changed jobs
- Removed jobs

This allows:

- Weekly intelligence
- Trend detection
- Emerging signal identification
- Alert surfaces

Without temporal diffing, the system collapses into a crawler.

---

## 6. AI Insights Sidecar

AI operates as a structured sidecar:

- Reads deterministic artifacts
- Consumes structured inputs (no raw JD leakage)
- Is cache-keyed
- Is schema-validated
- Is fail-closed
- Is cost-guardrailed

AI never becomes source-of-truth.

AI enhances interpretation — not ranking authority.

---

## 7. Delivery Layer (API + Object Store)

Delivery surfaces artifacts for:

- Dashboard inspection
- Historical retrieval
- Forensic validation
- Product UI consumption

Object store paths are deterministic.

Latest-pointer models support product UX without breaking artifact immutability.

Delivery does not replace employer career pages.

SignalCraft is a discovery layer — not a content host.

---

# Core Architectural Guarantees

SignalCraft guarantees:

1. Determinism
   Identical inputs produce identical core outputs.

2. Replayability
   Historical runs can be inspected and reproduced.

3. Explainability
   Scores are traceable to structured signals.

4. Fail-Closed AI
   AI failures cannot corrupt core logic.

5. Cost Guardrails
   AI and embedding usage are bounded and measurable.

6. Legal Posture Integrity
   The system preserves attribution and source-of-record.

These guarantees are non-negotiable.

---

# Runtime Topology (Simplified)
[Provider Registry + Policy]
        |
        v
[Ingestion: Snapshot/Live] --> [Deterministic Normalization] --> [Identity Engine] --> [Scoring Engine]
        |
        +--> [History + Diff Engine] --> [Run Artifacts]
                                   |
                                   +--> [AI Insights Sidecar]
                                   |
                                   +--> [Delivery: API + Object Store]

---

# Multi-User Evolution Path

SignalCraft is currently single-operator deterministic-first.

Future evolution toward product:

### Candidate Isolation

- `candidate_id` becomes first-class.
- Run state partitions by candidate.
- No cross-user artifact leakage.

### Profile Ingestion

- Structured profile schema.
- Resume normalization pipeline.
- Profile hashing for deterministic cache invalidation.

### Artifact Namespacing

Future object store layout: /candidates/<candidate_id>/runs/<run_id>/…

Migration compatibility layers preserve earlier path formats.

### Trust Signals in UI

- Show provenance
- Show identity hash
- Show score explanation
- Show AI structured inputs (summarized)

Product UX will expose trust — not hide it.

---

# Legal-Aware Design

SignalCraft is architected as a discovery net.

It:

- Preserves original URLs
- Preserves provider attribution
- Avoids paywall circumvention
- Avoids CAPTCHA evasion
- Respects robots.txt
- Does not present itself as source-of-record

Users are expected to apply on the employer site.

SignalCraft drives traffic outward — it does not absorb it.

See:
- `docs/LEGAL_POSITIONING.md`
- `docs/LEGALITY_AND_ETHICS.md`

---

# Strategic Moat (Architecture-Level)

The moat is not scraping.

The moat is:

- Deterministic temporal identity tracking
- Artifact-backed explainability
- Controlled AI augmentation
- Cost-bounded intelligence
- Infra-grade execution discipline

Scraping can be copied.

Deterministic intelligence with forensic guarantees is far harder to replicate.

---

# Related Contracts

- `docs/OPERATIONS.md`
- `docs/RUN_REPORT.md`
- `docs/CI_SMOKE_GATE.md`
- `docs/ROADMAP.md`
