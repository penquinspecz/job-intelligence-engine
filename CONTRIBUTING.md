# Contributing to SignalCraft

Thank you for your interest in SignalCraft!

SignalCraft is currently source-available under a proprietary license (see LICENSE). At this stage, we are **not accepting external code contributions**. This policy may change in the future as the project evolves.

## What is Acceptable

You are welcome to:

- **Open an Issue** for:
  - Bug reports
  - Feature requests
  - Documentation suggestions
  - Clarification questions about usage, design, or architecture

Issues should be specific, actionable, and reproducible when possible.

> Tip: Use descriptive titles and include steps, environment info, or error outputs.

## What is Not Acceptable (For Now)

- Pull Requests containing code changes
- Modifications to core logic or scoring behavior
- Additions to providers, pipelines, or AI inference logic
- Splitting or refactoring major subsystems

These are currently closed because we are in an early product phase and the legal/ownership framework doesn’t support accepting upstream code from external contributors.

## Security Reports

Do **not** open public issues about security vulnerabilities or sensitive risks. Instead:

1. Review the root `SECURITY.md` for instructions on how to report vulnerabilities.
2. Use the GitHub Security Advisory flow, or follow the coordination process described there.

This protects both you and the project.

## Future Open Contribution Policy

At a later stage, we may accept code contributions under one of the following:

- A formal **Contributor License Agreement (CLA)**
- An uplifted open-sourcing model
- A distinct plugin/extensions system

If we adopt any of these, this document will be updated with clear instructions and templates.

## Code Style

Even though code contributions aren’t accepted yet, you can still refer to:

- The repository’s `.editorconfig`
- The formatting conventions enforced by `make format` and `make lint`

Your local environment can check these with:
```bash
make format
make lint
