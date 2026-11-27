# Lighthouse

Multi-Project AI Development Orchestrator.

Lighthouse coordinates development handoffs between AI collaborators through
GitHub, while preserving independent review and human ownership. It is a reusable
platform; Koios Cold will be its first real configured project.

## Governing architecture

Craig approved adoption of [Craig Architecture](docs/architecture/standards/Craig-Architecture.md)
and its four supplements on 2026-11-23:

- [Python guidance](docs/architecture/standards/Craig-Architecture-Python.md).
- [Planning and decomposition](docs/architecture/standards/Craig-Architecture-Planning-And-Decomposition.md).
- [AI contributor guidance](docs/architecture/standards/AI_Guidance/Craig-Architecture-AI-Guidance.md).
- [Local contract standard](docs/architecture/standards/Craig-Architecture-__ai__-Template.md).

These documents live in Lighthouse and use internal links. Craig also approved
the [system architecture](docs/architecture/proposal.md) and
[T00–T09 initial development plan](docs/development/initial-plan.md), including
the plan's bounded delegation to Codex, on 2026-11-23.

Craig approved the baseline of one local Python process, TOML project profiles,
and a SQLite workflow ledger on 2026-11-23. GitHub remains authoritative for
repository facts. The five policy decisions and remaining approval gates are in
the [review register](docs/decisions/open-questions.md).

Craig also approved the work-admission policy and delegated exact labels and
Issue fields to Codex. The [work intake contract](docs/development/work-intake.md)
records those conventions. The 2026-11-25 recovery amendment permits offline
provider-neutral foundation work while integration-specific gates remain closed.
It takes effect after its documentation PR merges; it starts no assignment.
The [T01 capability report](experiments/codex-review/README.md)
records one controlled exact-head Codex review and COMMENT. Production
orchestration and Dot handoff remain unproved; execution, acceptance and
concrete live activation still require their applicable approvals.

The approved rollout uses controlled Lighthouse work for integration proofs and
keeps Koios as the first real project, inactive until its profile is verified and
approved for activation. Concrete live targets require separate approval.

The [architecture and initial-plan package](docs/README.md) is approved. Codex may
define and publish bounded task Issues and select compatible project-local
versions and dependency pins within that plan. Implementation starts from the
approved baseline on `development` after the planning PR merges; live execution
retains its explicit task gates. The orchestration design has not yet been implemented.

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

The orchestration workflow defaults to one active implementation writer per project.
Only authorized, unblocked, dependency-complete Issues are eligible. Ordinary
tasks wait for the preceding implementation PR to merge. The recovery amendment
parks draft PR #15 as an experimental reference outside that sequencing slot;
it does not complete T02, release uncertain executions or permit concurrent writers.
See the [amended sequence](docs/development/initial-plan.md) and
[verification selection policy](docs/development/verification-contract.md).
The orchestration engine has not been implemented.

## Contributor entry points

Read [agent instructions](AGENTS.md), the [root local contract](__ai__.md), and the
[verification contract](docs/development/verification-contract.md) before changing
the project. This repository is currently establishing its documentation and
development foundation.

## Install and verify the Python foundation

Use an existing CPython 3.14.x (64-bit AMD64) on Windows. From the repository
root in PowerShell, with that interpreter available as `python`:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --no-deps -r requirements-dev.lock
.\.venv\Scripts\python.exe -m pip install --no-build-isolation --no-deps -e .
.\.venv\Scripts\python.exe -m lighthouse --help
.\.venv\Scripts\python.exe -m lighthouse --version
```

The CLI provides help, the installed version, and read-only `status` for an
existing ledger. Those paths do not start orchestration or contact providers.
The separately gated foreground review entry requires an exact private
selection. Unsupported arguments are rejected. See the
[verification contract](docs/development/verification-contract.md) for
the test, lint, and type checks and the clean-room install procedure.

## Offline configuration (T03)

The Python configuration boundary validates shared service settings and explicit
project TOML profiles offline. See the [schema and examples](docs/development/configuration.md).
The [T07 foreground review entry](docs/development/review-runner.md) selects one existing committed review with explicit private settings. Automatic discovery or activation
is implemented.
