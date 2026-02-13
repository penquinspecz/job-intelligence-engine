# Security Policy

SignalCraft takes security seriously. If you discover a vulnerability, please report it privately so we can investigate and address it.

## Reporting a Vulnerability

**Preferred:** GitHub Security Advisories  
Use the repository’s “Report a vulnerability” flow (Security tab). This is the fastest way to get a private thread with maintainers.

**Email:** Not available yet  
We are intentionally not publishing a security mailbox until our intake process is staffed and tested. If GitHub Advisories are unavailable for you, open a minimal GitHub issue that says only: “Security report — please enable private reporting or contact me,” and do **not** include technical details.

## What to Include

Please include enough detail to reproduce and validate the issue:

- A clear description of the impact (what an attacker can do)
- Affected component(s) and version/commit (e.g., `main` at SHA)
- Reproduction steps or a proof-of-concept (safe, non-destructive)
- Any relevant logs, stack traces, or artifact paths
- Suggested fix or mitigation (if you have one)

**Do not** include secrets, tokens, or private data in your report.

## Coordinated Disclosure

We follow coordinated disclosure:

- Report privately first
- We will acknowledge receipt as soon as practical
- We will work with you on validation, severity, and remediation
- Public disclosure should wait until a fix is available or a coordinated timeline is agreed

## Scope

### In scope
- Code in this repository
- First-party runtime behavior (CLI, pipeline execution, dashboard API)
- Supply-chain risks in dependencies that affect SignalCraft execution

### Out of scope
- Vulnerabilities in third-party career sites SignalCraft indexes
- Social engineering, phishing, or physical attacks
- DoS against external sites (including any testing that impacts a target site)
- Attacks that require you to bypass paywalls, CAPTCHAs, login walls, or other access controls  
  (SignalCraft explicitly does **not** do this; reports requiring it aren’t actionable.)

## Supported Versions

- We support the latest `main` branch.
- Releases/tags may receive fixes at our discretion, but `main` is the primary supported line.

## Safety, Data, and Secrets

SignalCraft is designed to minimize sensitive data handling:

- **No secrets in the repo** (and we will remove any discovered secrets immediately)
- Runs produce artifacts under `state/` and may include scraped **public** job posting text/metadata
- The pipeline includes redaction/scanning guardrails to reduce accidental secret exposure risk

If your report involves data handling concerns, include:
- Which artifact(s) are impacted
- Whether the issue causes unintended retention, exposure, or publication

## Dependency & Supply Chain

- Dependencies are managed via the repo’s dependency contract (lock/pins where applicable)
- We prioritize fixes based on severity, exploitability, and operational impact
- We may temporarily mitigate by disabling a feature path (fail-closed) if that is the safest short-term option

## Safe Harbor

We welcome good-faith security research intended to improve SignalCraft security. Please:
- Avoid privacy violations, data destruction, and service disruption
- Avoid testing against third-party targets in a way that could impact them
- Use offline/snapshot modes where possible for reproduction

## On-Prem Exposure Notes

- Preferred exposure path for small trusted traffic is Cloudflare Tunnel + Cloudflare Access.
- Alternative path is `kubectl port-forward` from a trusted host with strict host firewall rules.
- Direct WAN ingress/NAT forwarding to dashboard is not recommended.
- On-prem hardened overlays should include ingress rate limiting, secure headers, and a baseline `NetworkPolicy`.
- Dashboard artifact serving must remain constrained to indexed run artifacts (no arbitrary filesystem reads).
- Keep ops/manifests hardening and dashboard application hardening independently testable and receipted.
