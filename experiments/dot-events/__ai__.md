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

Current source wiring is described in the
[capture-only operator runbook](t02-capture-operator-runbook.md). The fixed
operator selects the standalone coordinator, not a controller-owned role
route. The coordinator rechecks exact approval and local facts, consumes one
durable reservation, then creates original Jobs before the role launch lane.
The transferred supervisor selects the fixed listener and runtime adapters.
Channel and receipt binding do not by themselves prove Windows capability
origin. The installed release binding is absent; direct entries stay held.
The [approved bounded trust model](t02-capture-provenance-design.md) uses the
existing trusted operator account, not a protected broker or hostile
same-account isolation. The separately scoped
[selected native proof](test_t02_selected_native.py) is opt-in only and
does not install or enable any release entry.

The component notes below describe their independently reviewed offline scope;
they are not a claim of native selected-process or operational readiness.

- [t02_event_native_fixture.py](t02_event_native_fixture.py) and
  [test_t02_event_native.py](test_t02_event_native.py): only the fixed local
  Python ownership fixture and independent witness, not vendor execution.
- [t02_event_capture.py](t02_event_capture.py) and
  [test_t02_event_capture.py](test_t02_event_capture.py): dormant capture-only
  authenticated RPC-to-private-store experiment; no network/sender or activation.

- [t02_capture_evidence.py](t02_capture_evidence.py): offline fixed-scope approval policy, with a fixed credentialless reader selected only by the held composition.
- [t02_capture_operator.py](t02_capture_operator.py): inert entry; operational selectors always hold.

- [t02_capture_packet.py](t02_capture_packet.py): strict capture-only packet and canonical digest, no local attestation.
- [t02_capture_lifecycle.py](t02_capture_lifecycle.py): injected guarded sequencing used for offline proof; the selected executable uses the standalone coordinator.
- [t02_capture_watchdog.py](t02_capture_watchdog.py): inert deadline policy; no scheduled or native watchdog host.
- [t02_capture_local.py](t02_capture_local.py): compare exact checkout and file facts; the native local observer is separately bounded and release-held.

- [t02_capture_windows_host.py](t02_capture_windows_host.py): dormant fixed supervisor Job containment, mock-only checks.
- [t02_capture_supervisor.py](t02_capture_supervisor.py) and [t02_capture_host_channel.py](t02_capture_host_channel.py): fixed role control and status over the bounded transport, with activation held.

- [t02_capture_pipe_owner.py](t02_capture_pipe_owner.py), [t02_capture_windows_pipe.py](t02_capture_windows_pipe.py), and [t02_capture_private_channel.py](t02_capture_private_channel.py): private channel provisioning, bounded I/O, and fixed command frames for the selected helper graph.
- [t02_capture_role_handles.py](t02_capture_role_handles.py): exact locally owned Job/root handoff and stop witness; not an integrated live role.
- [t02_capture_peer.py](t02_capture_peer.py): guarded peer bootstrap through fake capability events; no native helper entry activation.

- [t02_capture_native_peer.py](t02_capture_native_peer.py): dormant fixed native frame/stop wait.
- [t02_capture_terminal.py](t02_capture_terminal.py), [t02_capture_roles.py](t02_capture_roles.py): sole watchdog terminal owner and fixed role factories; no live entry.

- [t02_capture_bootstrap.py](t02_capture_bootstrap.py), [t02_capture_host_entry.py](t02_capture_host_entry.py), and [t02_capture_listener.py](t02_capture_listener.py): inherited capabilities, claimed-store binding and fixed listener helper; direct entry held.
- [t02_capture_detached.py](t02_capture_detached.py) and [t02_capture_local_windows.py](t02_capture_local_windows.py): detached cleanup policy and bounded local evidence, tested with fakes.

- [t02_capture_handoff.py](t02_capture_handoff.py), [t02_capture_transfer.py](t02_capture_transfer.py), and [t02_capture_owned_jobs.py](t02_capture_owned_jobs.py): authenticated one-use pipe transfer and two preowned Jobs; code graph remains held.

The fixed private capture installation remains absent. See the [operator runbook](t02-capture-operator-runbook.md) for the versioned sibling profile and guarded install/disable planning. No selector, test flag or environment override permits an operational profile or release.
