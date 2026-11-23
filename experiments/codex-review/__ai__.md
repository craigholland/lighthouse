# Codex Review Experiment Local Contract

## Last Verified (CI)

No CI is configured. Exact-head offline evidence belongs to the T01 PR.

## Scope

Files in this experiment only. Scratch journals, local venvs, Lead credentials
and personal settings are not tracked.

## Purpose

Prove conservative recovery and selected SDK schema compatibility offline. Do
not represent synthetic receipts as GitHub reviews.

## Architectural Rules

Save intent before an effect. Resolve ambiguity using attributed observations
or hold; do not replay. Keep accepted scope fixed and separate receipt,
acceptance and completion. Live execution remains separately gated.

## Allowed Dependencies

Experiment lock and Python standard library only. SDK use is limited to
public schema types; no construction, subprocess, network or credential access
from experiment entry paths. Only the designated offline Windows test launches
the fixed harmless Python fixture and its descendants.

## Public API / Key Exports

Local help/dry-run and separately held opt-in operator entry; no public package API.

## File Index

- [proof.py](proof.py): offline-only composition and CLI.
- [harness.py](harness.py): synthetic worker/review boundaries and journal recovery.
- [sdk_schema.py](sdk_schema.py): response schema parsing without a client.
- [test_proof.py](test_proof.py) and [test_sdk_schema.py](test_sdk_schema.py):
  synthetic recovery, safety fences and SDK schema fixtures.
- [authorization.py](authorization.py): canonical packet, trusted evidence validation and claim.
- [supervisor.py](supervisor.py): injected, deadline-bound control of distinct proof jobs.
- [windows_job.py](windows_job.py): native Job Object operations scoped to the harmless fixture.
- [live.py](live.py) and [live_stage.py](live_stage.py): gated role composition and private control.
- [sdk_worker.py](sdk_worker.py) and [github_transport.py](github_transport.py): deferred, role-separated provider boundaries.
- [README.md](README.md): offline capability report and disabled approval template.

## Known Gaps / Future-State Notes

No live capability, controlled review, production ledger or approval is proved.

## Cross-Folder Contracts

Do not import this experiment into the installable Lighthouse package or add
its SDK to the foundation runtime/dev lock.

## Verification Contract

Use the [project verification contract](../../docs/development/verification-contract.md)
from the repository root and record which exact head was checked.
