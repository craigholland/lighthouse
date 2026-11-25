# Dot Events Experiment Local Contract

## Last Verified (CI)

No CI is configured. Local check evidence belongs to the exact draft PR head
and is not evidence of real event delivery or worker dispatch.

## Scope

T02 Phase A records, an offline known-worker/marker proof, and a separate
worker-free event source with dormant fixed transport adapters. No live
connection, setup or settings.

## Purpose

Model the known-worker handoff and receiver-owned pre-effect claim, and keep
the unresolved hosted integration evidence explicit.

## Architectural Rules

Signal, continuation intent, acknowledgement, attributable known-worker
acceptance, local start and completion are separate. Use one immutable
synthetic reservation; unknown outcomes hold without automatic retry,
replacement, fallback or reinitialization. Conflicting valid turns for the
same binding durably block new marker admission and attributed completion;
repeated observations cannot clear the hold. The receiver owns the fixed marker.

## Allowed Dependencies

Standard library and existing test tools; no runtime or package dependency.
Use private disposable SQLite state, not the production ledger.

## Public API / Key Exports

No installable API. The worker-free event probe exposes only the synthetic CLI and typed review boundaries; concrete backend code is dormant and activation stays disabled. The experiment's entry provides only help and synthetic
dry-run. The in-process fake port can continue and inspect one bound worker;
it has no worker creation operation.

## File Index

- [README.md](README.md): proof scope, durability limits and historic assessment.
- [t02_receiver.py](t02_receiver.py): immutable work, local durable owner and marker.
- [t02_fixture.py](t02_fixture.py): synthetic work and fake known-worker port.
- [t02_proof.py](t02_proof.py): inert entry.
- [t02_process_fixture.py](t02_process_fixture.py) and
  [test_t02_receiver.py](test_t02_receiver.py): bounded Python and SQLite evidence.

- [t02_events_probe.py](t02_events_probe.py): separate fake-only event probe entry.
- [t02_event_rpc.py](t02_event_rpc.py): pinned protocol discovery boundary.
- [t02_event_source.py](t02_event_source.py): durable private subscription and budgets.
- [t02_event_types.py](t02_event_types.py): strict callback and signing contract.
- [t02_event_gate.py](t02_event_gate.py): proposed exact-authority and lifecycle ports.
- [t02_event_evidence.py](t02_event_evidence.py): strict packet and provider evidence parsing.
- [t02_event_assembly.py](t02_event_assembly.py): fake-only composed loopback, TLS and owned-lifecycle boundaries.
- [t02_event_https.py](t02_event_https.py), [t02_event_loopback.py](t02_event_loopback.py),
  and [t02_event_windows.py](t02_event_windows.py): dormant fixed stdlib backends.
- [t02_event_production.py](t02_event_production.py): fixed composition, unreachable from CLI.
- [t02_event_dns.py](t02_event_dns.py): owned Windows overlapped resolver and cancellation acknowledgement.
- [test_t02_event_backends.py](test_t02_event_backends.py) and
  [test_t02_event_deadlines.py](test_t02_event_deadlines.py): fake-only low-level I/O and readiness checks.
- [test_t02_event_probe.py](test_t02_event_probe.py) and
  [test_t02_event_assembly.py](test_t02_event_assembly.py): effect, denial and deadline evidence.

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


## Native ownership and dormant capture preparation

- [t02_event_native_fixture.py](t02_event_native_fixture.py) and
  [test_t02_event_native.py](test_t02_event_native.py): only the fixed local
  Python ownership fixture and independent witness, not vendor execution.
- [t02_event_capture.py](t02_event_capture.py) and
  [test_t02_event_capture.py](test_t02_event_capture.py): dormant capture-only
  authenticated RPC-to-private-store experiment; no network/sender or activation.

- [t02_capture_evidence.py](t02_capture_evidence.py): offline fixed-scope approval policy, with no default provider.
- [t02_capture_operator.py](t02_capture_operator.py): inert entry; operational selectors always hold.

- [t02_capture_packet.py](t02_capture_packet.py): strict capture-only packet and canonical digest, no local attestation.
- [t02_capture_lifecycle.py](t02_capture_lifecycle.py): synthetic guarded sequencing, no concrete role owner or CLI wiring.
- [t02_capture_watchdog.py](t02_capture_watchdog.py): inert deadline policy; no scheduled or native watchdog host.
- [t02_capture_local.py](t02_capture_local.py): compare injected exact checkout and file facts; no native observer.

- [t02_capture_windows_host.py](t02_capture_windows_host.py): dormant fixed supervisor Job containment, mock-only checks.
- [t02_capture_supervisor.py](t02_capture_supervisor.py) and [t02_capture_host_channel.py](t02_capture_host_channel.py): fixed role control and status policy; no native transport or activation.

- [t02_capture_pipe_owner.py](t02_capture_pipe_owner.py), [t02_capture_windows_pipe.py](t02_capture_windows_pipe.py), and [t02_capture_private_channel.py](t02_capture_private_channel.py): private channel provisioning, bounded I/O, and fixed command frames, not connected to the helper entry.
- [t02_capture_role_handles.py](t02_capture_role_handles.py): exact locally owned Job/root handoff and stop witness; not an integrated live role.
- [t02_capture_peer.py](t02_capture_peer.py): guarded peer bootstrap through fake capability events; no native helper entry activation.
