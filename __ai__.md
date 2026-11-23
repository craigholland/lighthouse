# Lighthouse Root Local Contract

## Last Verified (CI)

No CI pipeline is configured. No CI result or independent QA is claimed. Local
verification evidence belongs to the PR and identifies its checked commit.

## Scope

The repository's tracked documentation and bootstrap instructions. Local virtual
environments, IDE settings, credentials, and Git internals are outside this scope.
This parent contract governs the current small documentation tree.

## Purpose

Maintain the governing standards, adopted architecture and initial plan for a
reusable development-orchestration project. Distinguish approved design and
delegated work from implemented behavior and demonstrated integration capability.

## Architectural Rules

Apply [Craig Architecture](docs/architecture/standards/Craig-Architecture.md) and
the approved role and branch binding in the [README](README.md), and the adopted
[system architecture](docs/architecture/proposal.md) and
[initial plan](docs/development/initial-plan.md). Craig owns consequential
decisions and specific merge authorizations.

The approved runtime baseline is one local Python process, TOML project profiles
and a SQLite workflow ledger, with GitHub authoritative for repository facts.
The approved [work intake contract](docs/development/work-intake.md) governs
readiness, dependencies, captured scope, priority and PR linkage. Codex selected
its exact labels and fields under Craig's explicit delegation.
The approved feasibility-first stage puts foundation and Codex/Dot proofs ahead
of production orchestration. Its capabilities remain unproven; Craig must accept
the evidence before engine construction and production dispatch. Craig approved
the overall architecture/plan and delegated bounded task publication and compatible
project-local version/pinning choices to Codex. Implementation waits for the
planning PR to merge; concrete live-target/access approvals remain separate.
The approved rollout uses controlled Lighthouse proof work and keeps Koios as the
first real project, inactive until its bindings are verified and Craig approves
activation. Concrete live targets require separate approval before execution.

## Allowed Dependencies

Governing documents link to files within this repository. The copied standards
do not depend on another project's checkout or verification contract. Future
core logic must remain independent of project profiles and concrete adapters.

## Public API / Key Exports

The current public surfaces are documentation and contributor instructions.
There is no runtime package, CLI, configuration schema, or implemented adapter.
The architecture package defines approved design and intake contracts, including
evidence gates for integration capabilities that remain unproven.

## File Index

- [README.md](README.md): project identity, adopted standards, and development profile.
- [AGENTS.md](AGENTS.md): agent orientation and approved authority boundaries.
- [.gitignore](.gitignore): excludes generated outputs and local environment/IDE metadata.
- [docs/architecture/standards/](docs/architecture/standards/): the five adopted standards.
- [docs/development/verification-contract.md](docs/development/verification-contract.md):
  runnable checks and their current evidence limits.
- [docs/README.md](docs/README.md): index of the adopted architecture, integration
  assessment, initial plan, bounded delegation and decision register.
- [docs/development/work-intake.md](docs/development/work-intake.md): approved
  admission policy and delegated intake conventions; not yet implemented.

## Known Gaps / Future-State Notes

The approved design has no runtime implementation yet. Compatible supported
Python versions and reproducible dependency pins will be established during
T00/T01 under Codex's bounded delegation. The five policy questions and overall
adoption are resolved; future evidence/live-execution gates remain recorded in
the [decision register](docs/decisions/open-questions.md). SDK compatibility and
Dot's full delivery/worker chain still require evidence. There is no application
test suite or CI pipeline.
Ruff and mypy commands are not yet configured. Basic branch protections do not
enforce the named reviewer or owner-only merging; planned engine checks detect
violations and hold work. Stronger platform enforcement is outside the initial scope.

## Cross-Folder Contracts

The Python supplement delegates project verification to Lighthouse's own
[verification contract](docs/development/verification-contract.md). AI contributor
guidance uses the README as the project development profile and this file as the
nearest local contract until a narrower ownership boundary needs one.

## Verification Contract

Run the commands in the [project verification contract](docs/development/verification-contract.md)
from the repository root. Report documentation checks separately from environment
readiness and future application tests. Never infer a passing test suite from an
installed test runner.
