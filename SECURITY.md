# Security Policy

## Reporting a Vulnerability

Please report suspected security vulnerabilities to:
- Email: `security@your-domain.com`
- GitHub Security Advisories for this repository (if enabled)

Please do not open public GitHub issues with detailed vulnerability information.

## Disclosure Expectations

SignalCraft follows a coordinated disclosure approach:
- Report privately first.
- Allow time for triage, validation, and remediation.
- Public disclosure should occur only after a fix is available or coordinated timing is agreed.

## Scope

In scope:
- Code in this repository and its first-party runtime behavior.

Out of scope:
- Third-party services, infrastructure, or vendor-managed systems.
- Vulnerabilities in external websites that SignalCraft indexes.
- Scraping targets themselves (career sites) as vulnerability-report scope.

## Supported Versions

- `main` branch only.

## Dependency and Supply Chain Policy

SignalCraft uses dependency monitoring and pinned dependency workflows (including Dependabot where configured) with best-effort maintenance.

No warranty is provided for third-party dependency vulnerabilities; remediation is prioritized based on severity and operational impact.

## Data Handling and Secrets

- Do not include secrets, tokens, credentials, or private data in vulnerability reports.
- The repository should not contain secrets by design.
- SignalCraft includes redaction/scanning guardrails in the pipeline to reduce accidental secret exposure risk.
