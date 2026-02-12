# Changelog

All notable changes to SignalCraft are documented in this file.

The format is based on Keep a Changelog and follows SemVer.

## [Unreleased]

- _No unreleased changes yet._

## [v0.1.0] - 2026-02-12

Theme: Deterministic Core + Guardrailed AI Foundation

### Determinism & Replayability

- Established deterministic run contracts with strict artifact validation and replay tooling.
- Added run identity/provenance history, normalized exit code policy, and fail-closed verification paths.
- Hardened smoke/CI truth gates with offline-friendly checks and deterministic snapshot handling.
- Added proof receipts and contract tests across milestone deliveries to keep behavior auditable.

### Providers

- Introduced config-driven provider contracts with deterministic enabled/disabled filtering.
- Landed multi-provider support receipts and deterministic provider selection behavior.
- Added Hugging Face support in `jsonld` mode with contract-focused tests and deterministic fixture coverage.

### Semantic Safety Net

- Added deterministic semantic embedding scaffold with local cache + semantic artifacts.
- Introduced bounded semantic boost policy (guardrailed, replayable) and sidecar/boost execution behavior.
- Fixed semantic short-circuit handling so semantic evidence is produced deterministically when enabled.
- Added offline proof receipts and stronger contract tests for semantic execution paths.

### AI Insights

- Added weekly AI insights with guarded, cached execution and deterministic fallbacks/stub behavior.
- Upgraded to structured weekly insights inputs grounded in deterministic run artifacts.
- Enforced strict cache-key inputs for prompt/versioned AI generation paths.

### Ops/Deploy/DR

- Added Kubernetes/EKS deployment overlays, runbooks, and reproducible operational proof steps.
- Added DR rehearsal scaffolding, backup/restore workflows, and cloud verification contracts.
- Documented CI smoke gate failure modes and operational debugging workflows.

### Dashboard

- Added a minimal FastAPI dashboard API for run/artifact browsing with deterministic content serving.
- Expanded forensic run visibility for semantic/AI/cost truth without introducing UI-side coupling.
- Kept dashboard dependencies optional with clear install/runtime guidance.
