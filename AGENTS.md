# Lighthouse agent instructions

Read the [README](README.md) for the project development profile, then the
[root local contract](__ai__.md), [Craig Architecture](docs/architecture/standards/Craig-Architecture.md),
and the applicable supplements linked there.

Use the [verification contract](docs/development/verification-contract.md) for
current commands and the limits of their evidence.

Codex is the Lead Engineer; Dot is the Implementation Engineer. Preserve their
separate App identities, credentials, and checkouts. Craig retains consequential
decision and merge authority. Do not merge a PR without Craig's authorization for
that specific operation.

Implementation PRs target `development`. Release promotion targets `main` and
requires Craig's authorization. Do not begin substantive orchestration
implementation or create its implementation Issue backlog before Craig approves
the system architecture and initial development plan.

Keep credentials, tokens, private keys, and local machine configuration outside
tracked files, logs, examples, and test fixtures. Project-specific integrations
and profiles must not introduce Koios-specific assumptions into the core.
