# Lighthouse

Multi-Project AI Development Orchestrator.

Lighthouse coordinates development handoffs between AI collaborators through
GitHub, while preserving independent review and human ownership. It is a reusable
platform; Koios Cold will be its first configured project.

## Governing architecture

Craig approved adoption of [Craig Architecture](docs/architecture/standards/Craig-Architecture.md)
and its four supplements on 2026-11-23:

- [Python guidance](docs/architecture/standards/Craig-Architecture-Python.md).
- [Planning and decomposition](docs/architecture/standards/Craig-Architecture-Planning-And-Decomposition.md).
- [AI contributor guidance](docs/architecture/standards/AI_Guidance/Craig-Architecture-AI-Guidance.md).
- [Local contract standard](docs/architecture/standards/Craig-Architecture-__ai__-Template.md).

These documents live in Lighthouse and use internal links. The detailed system
architecture and initial implementation plan still require Craig's approval.

The [architecture and initial-plan package](docs/README.md) is now available for
review. It is proposed, with unresolved decisions recorded explicitly; it does
not authorize orchestration implementation or publication of its Issue backlog.

## Development profile

- **Craig — Project Owner:** sets direction, approves consequential decisions,
  and personally merges approved PRs. Each merge requires his specific authorization.
- **Codex — Lead Engineer:** defines bounded work and acceptance criteria,
  coordinates Dot, and independently reviews Dot's PRs. Bootstrap documentation
  authored by Codex requires another reviewer; self-review is not independent QA.
- **Dot — Implementation Engineer:** implements authorized tasks, creates branches
  and PRs, runs verification, and addresses review findings.

Each agent uses its own GitHub App identity and a separate checkout. Credentials
and machine-specific configuration stay outside version control.

`development` is the default branch and integrates active work. Task branches
target `development` through PRs. At a stable release point, `development` is
promoted to `main` through an owner-authorized merge and tagged as a release.
`main` holds released snapshots after the first release.

Both branches require one approving review, invalidate stale approvals when the
reviewed changes change, and block force pushes and deletion. These requirements
also apply to administrators. Auto-merge is disabled. The basic GitHub review
gate does not yet enforce the Codex reviewer identity or Craig-only merging.

The orchestration workflow defaults to one active implementation task per project.
Only authorized, unblocked, dependency-complete Issues are eligible. The next
implementation task waits for the preceding PR to merge. The orchestration
engine has not been implemented.

## Contributor entry points

Read [agent instructions](AGENTS.md), the [root local contract](__ai__.md), and the
[verification contract](docs/development/verification-contract.md) before changing
the project. This repository is currently establishing its documentation and
development foundation.
