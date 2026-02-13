# Legal Positioning

## Intent

SignalCraft is a discovery layer for career opportunities, not a replacement for employer career sites or a standalone job board destination.

The product is designed to help users identify relevant opportunities efficiently, then route them to original sources for verification and application.

## Compliance Guardrails

SignalCraft implementation and operations are grounded in explicit compliance constraints:

- Robots respect: crawling behavior is expected to honor robots and policy controls as configured.
- Rate limiting: per-host throttling and politeness controls reduce operational and policy risk.
- No paywall bypass: the platform does not attempt to circumvent access controls.
- No CAPTCHA circumvention: anti-bot barriers are treated as a stop condition, not an obstacle to defeat.
- Attribution preserved: source links and provenance are retained so users can trace and verify origin.

## Legal Theory

SignalCraft’s operating model is based on a narrow, practical posture:

- Publicly accessible job postings are indexed as discovery signals.
- The core product value is transformative organization: normalization, ranking, diffing, and relevance scoring.
- Output is designed to drive users back to source pages, supporting original publishers as the final record of truth.

## Risk Areas

Key risk areas remain active and should be managed explicitly:

- Scraping escalation risk: site defenses and tolerance can change over time.
- Terms-of-service variability: terms differ by publisher and may evolve without notice.
- Jurisdiction and interpretation variance: legal expectations may differ across regions and contexts.

Mitigation strategy:

- Keep provider policy decisions explicit and auditable.
- Maintain conservative defaults for collection behavior.
- Use deterministic artifacts and provenance to support review and incident response.
- Disable or limit providers quickly when policy confidence is low.

## Long-Term Strategy

SignalCraft’s long-term strategy prioritizes durable access and trust:

- Partnerships over scraping arms race: pursue cooperative data access where possible.
- API-first when available: prefer official integration points over brittle collection paths.
- Opt-out policy: support exclusion requests through clear provider disablement workflows.

This positioning aligns product value with responsible operation and long-term platform defensibility.
