# Lighthouse Root Local Contract

## Last Verified (CI)

No CI pipeline is configured. No CI result or independent QA is claimed. Local
verification evidence belongs to the PR and identifies its checked commit.

## Scope

Tracked documentation, the Python foundation under `src/lighthouse/`, and its
tests and packaging/tool configuration. The offline Codex review experiment has a narrower local contract. Local virtual environments, IDE
settings, credentials, and Git internals are outside this scope.

## Purpose

Maintain the governing standards and development foundation for a reusable
development-orchestration project. The installable package currently exposes
only CLI help and version. Distinguish approved design from implemented
behavior and demonstrated integration capability.

## Architectural Rules

Apply [Craig Architecture](docs/architecture/standards/Craig-Architecture.md)
and the role and branch binding in the [README](README.md), and the adopted
[system architecture](docs/architecture/proposal.md) and
[initial plan](docs/development/initial-plan.md). Craig owns consequential
decisions and specific merge authorizations.

The approved runtime baseline remains one local Python process, TOML profiles
and a SQLite workflow ledger, with GitHub authoritative for repository facts.
The [work intake contract](docs/development/work-intake.md) governs the design of
readiness, dependencies, captured scope, priority, and PR linkage.
Provider-backed intake is not
implemented. Keep the foundation free of live integration behavior.

The 2026-11-25 recovery amendment, effective after its documentation PR merges,
allows bounded offline provider-neutral foundations without T02 completion.
It parks draft PR #15 outside the implementation sequencing slot, preserves one
active writer and ordinary merge-before-next-task rules, and never releases an
uncertain live execution. Follow the plan's capability-specific gates and the
verification contract's change/checkpoint selection policy. Each later task still needs its
own ready assignment; no runtime parking feature or live action is authorized.

## Allowed Dependencies

The runtime depends only on the standard library. Build and development tools
are version-pinned; see [pyproject.toml](pyproject.toml) and
[requirements-dev.lock](requirements-dev.lock). Governing standards link
within this repository and do not rely on another checkout. The experiment pins its SDK separately and is not importable by the installed package.

## Public API / Key Exports

`python -m lighthouse --help` describes the available options.
`python -m lighthouse --version` reports installed package metadata.
Unsupported arguments exit nonzero. Import and these commands do not open
external resources or start work. See the offline
[configuration contract](docs/development/configuration.md) and
[pure workflow decisions](docs/development/workflow.md), and the explicit
[offline SQLite ledger](docs/development/ledger.md).
The [GitHub mapper](docs/development/github-facts.md) only normalizes supplied facts.

## File Index

- [README.md](README.md) and [AGENTS.md](AGENTS.md): setup, contributor roles, and authority.
- [pyproject.toml](pyproject.toml) and [requirements-dev.lock](requirements-dev.lock):
  package metadata, tool settings, and Windows dependency pins.
- [src/lighthouse/__main__.py](src/lighthouse/__main__.py): module entry point.
- [src/lighthouse/cli.py](src/lighthouse/cli.py): parses help and version arguments.
- [tests/test_cli.py](tests/test_cli.py): tests the real installed entry point.
- [docs/README.md](docs/README.md): index of the adopted architecture and plan.
- [Codex review experiment](experiments/codex-review/__ai__.md): offline recovery evidence and one exact-head controlled live proof, not production readiness.
- [Verification contract](docs/development/verification-contract.md): commands and evidence limits.

## Known Gaps / Future-State Notes

No production orchestration engine, production
adapters or CI are implemented. The separately gated T01 experiment is not
a production integration. Compatibility is targeted to CPython 3.14.x on Windows
AMD64, not asserted for other environments. Integration proofs and production
activation retain their approval gates in the
[decision register](docs/decisions/open-questions.md). Basic branch protection
does not enforce the named reviewer or owner-only merging.

## Cross-Folder Contracts

The CLI version comes from installed distribution metadata, not a duplicated
runtime constant. Tests exercise the installed module from outside the checkout
without `PYTHONPATH` wiring. The
[Python guidance](docs/architecture/standards/Craig-Architecture-Python.md)
delegates project verification to the Lighthouse verification contract.

## Verification Contract

Run the [project verification contract](docs/development/verification-contract.md)
from the repository root unless it calls for an outside-directory smoke check.
Local results are not CI or independent review evidence. The T01 experiment's
private Git binding and two read-only checkout checks do not grant execution
authority or affect the installable foundation.
