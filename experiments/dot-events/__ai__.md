# Dot Events Experiment Local Contract

## Last Verified (CI)

No CI is configured. Local check evidence belongs to the exact draft PR head
and is not evidence of real event delivery or worker dispatch.

## Scope

T02 Phase A records and the isolated offline one-worker/one-marker proof; no
native provider, transport implementation, live connection, setup or settings.

## Purpose

Model the known-worker handoff and receiver-owned pre-effect claim, and keep
the unresolved hosted integration evidence explicit.

## Architectural Rules

Signal, continuation intent, acknowledgement, attributable known-worker
acceptance, local start and completion are separate. Use one immutable
synthetic reservation; unknown outcomes hold without automatic retry,
replacement, fallback or reinitialization. The receiver owns the fixed marker.

## Allowed Dependencies

Standard library and existing test tools; no runtime or package dependency.
Use private disposable SQLite state, not the production ledger.

## Public API / Key Exports

No installable API. The experiment's entry provides only help and synthetic
dry-run. The in-process fake port can continue and inspect one bound worker;
it has no worker creation operation.

## File Index

- [README.md](README.md): proof scope, durability limits and historic assessment.
- [t02_receiver.py](t02_receiver.py): immutable work, local durable owner and marker.
- [t02_fixture.py](t02_fixture.py): synthetic work and fake known-worker port.
- [t02_proof.py](t02_proof.py): inert entry.
- [t02_process_fixture.py](t02_process_fixture.py) and
  [test_t02_receiver.py](test_t02_receiver.py): bounded Python and SQLite evidence.

## Known Gaps / Future-State Notes

Custom tunneled event eligibility and exact event-triggered native continuation
are unproved. Proof authority, live access, retention, cost and acceptance
require later contracts. This is not a general guarantee against manual work.

## Cross-Folder Contracts

Follow the adopted [architecture](../../docs/architecture/proposal.md) and
[initial plan](../../docs/development/initial-plan.md); no new transport
selection, packaging, dependency, production orchestration or T01 changes.

## Verification Contract

Use the [Windows inert checks](../../docs/development/verification-contract.md#offline-dot-known-worker-experiment).
Only the designated harmless fixture processes and disposable state are used.
