# Lighthouse Root Local Contract

## Last Verified (CI)

No CI pipeline is configured. No CI result or independent QA is claimed. Local
verification evidence belongs to the PR and identifies its checked commit.

## Scope

The repository's tracked documentation and bootstrap instructions. Local virtual
environments, IDE settings, credentials, and Git internals are outside this scope.
This parent contract governs the current small documentation tree.

## Purpose

Establish a reusable development-orchestration project's governing standards and
contributor context before implementation. Record approved decisions alongside
architecture and development-plan proposals, preserving their distinct authority.

## Architectural Rules

Apply [Craig Architecture](docs/architecture/standards/Craig-Architecture.md) and
the approved role and branch binding in the [README](README.md). Preserve the
distinction between adopted standards and proposed system design. Craig owns
consequential decisions and specific merge authorizations.

The approved runtime baseline is one local Python process, TOML project profiles
and a SQLite workflow ledger, with GitHub authoritative for repository facts.
The approved [work intake contract](docs/development/work-intake.md) governs
readiness, dependencies, captured scope, priority and PR linkage. Codex selected
its exact labels and fields under Craig's explicit delegation.
The approved feasibility-first stage puts foundation and Codex/Dot proofs ahead
of production orchestration. Its capabilities remain unproven; Craig must accept
the evidence before production dispatch. Overall architecture/plan approval and
applicable concrete live-target/access approvals are still required for execution.
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
The architecture package distinguishes approved intake conventions from proposed
runtime contracts and their evidence gates.

## File Index

- [README.md](README.md): project identity, adopted standards, and development profile.
- [AGENTS.md](AGENTS.md): agent orientation and approved authority boundaries.
- [.gitignore](.gitignore): excludes generated outputs and local environment/IDE metadata.
- [docs/architecture/standards/](docs/architecture/standards/): the five adopted standards.
- [docs/development/verification-contract.md](docs/development/verification-contract.md):
  runnable checks and their current evidence limits.
- [docs/README.md](docs/README.md): index of the proposed architecture, integration
  assessment, initial plan and decision register; none authorizes implementation.
- [docs/development/work-intake.md](docs/development/work-intake.md): approved
  admission policy and delegated intake conventions; not yet implemented.

## Known Gaps / Future-State Notes

The remaining detailed architecture, initial plan, package layout, dependency
management and supported runtime versions await overall adoption or the plan's
proposed bounded delegation. The five policy questions are resolved; package
approval and future evidence/live-execution gates are recorded in the
[review register](docs/decisions/open-questions.md). Dedicated local Codex review
sessions are accepted; SDK compatibility and Dot's full delivery/worker chain
still require evidence. There is no application test suite or CI pipeline.
Ruff and mypy commands are not yet configured. Basic branch protections do not
enforce the named reviewer or owner-only merging; proposed engine checks detect
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
