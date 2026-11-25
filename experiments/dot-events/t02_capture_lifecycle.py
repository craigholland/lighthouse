"""Offline guarded sequencing; concrete independent ownership is not wired."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from t02_capture_evidence import CaptureEvidence
from t02_capture_local import LocalCaptureObservation, matches_local_capture
from t02_capture_packet import CapturePacket
from t02_event_capture import CaptureStore
from t02_event_types import Hold


class CaptureRoles(Protocol):
    """An independent owner must already enforce its non-extendable deadline."""

    def arm(self, cleanup_deadline_ms: int) -> None: ...
    def start_listener(self, intake_deadline_ms: int) -> None: ...
    def start_runtime(self, intake_deadline_ms: int) -> None: ...
    def wait_candidate(self, intake_deadline_ms: int) -> None: ...
    def signal_all(self) -> None: ...
    def confirmed_stopped(self, cleanup_deadline_ms: int) -> bool: ...


def guarded_capture(
    packet: CapturePacket,
    store: CaptureStore,
    evidence: CaptureEvidence,
    owner_ref: int,
    lead_ref: int,
    wall: Callable[[], int],
    monotonic: Callable[[], int],
    observe_local: Callable[[], LocalCaptureObservation],
    roles: CaptureRoles,
    *, supervisor_finalizes: bool = False,
) -> str:
    """Sequence an admitted capture over injected roles; no retry or live factory."""
    target = packet.approval
    sampled_wall = wall()
    sampled_mono = monotonic()
    intake = sampled_mono + packet.intake_cutoff_ms - sampled_wall
    cleanup = sampled_mono + target.cutoff_ms - sampled_wall

    def authorized() -> bool:
        return (
            monotonic() < intake and wall() < packet.intake_cutoff_ms
            and evidence.allows(target, owner_ref, lead_ref)
            and monotonic() < intake and wall() < packet.intake_cutoff_ms
        )

    def intake_wall() -> int:
        if monotonic() >= intake:
            return packet.intake_cutoff_ms
        return wall()

    if not authorized():
        return "denied"
    try:
        local = observe_local()
        if not matches_local_capture(packet, local) or not authorized():
            return "denied"
    except (Hold, OSError, KeyboardInterrupt):
        return "denied"
    if (not store.matches_operation(target.head, target.digest, target.activation_ms, packet.intake_cutoff_ms)
        or store.binding.proof_id != packet.proof_id or store.binding.principal != packet.principal):
        return "denied"
    try:
        store.claim(intake_wall)
    except (Hold, OSError):
        return "admission-unknown"

    attempted = False
    confirmed = True
    disposition = "held"
    try:
        if authorized():
            attempted = True
            roles.arm(cleanup)
            if authorized():
                roles.start_listener(intake)
                if authorized():
                    roles.start_runtime(intake)
                    if monotonic() < intake:
                        roles.wait_candidate(intake)
                    if store.status() == ("claimed", "captured"):
                        disposition = "candidate-held"
    except (Hold, OSError, TimeoutError, KeyboardInterrupt):
        disposition = "held"
    finally:
        stop_ok = False
        if attempted:
            try:
                roles.signal_all()
            except (Hold, OSError, KeyboardInterrupt):
                confirmed = False
        if not supervisor_finalizes:
            try:
                store.stop()
                stop_ok = store.status()[0] == "sealed"
            except (Hold, OSError, KeyboardInterrupt):
                stop_ok = False
        if attempted:
            try:
                observed = roles.confirmed_stopped(cleanup)
                confirmed = observed and confirmed
            except (Hold, OSError, KeyboardInterrupt):
                confirmed = False
        if supervisor_finalizes:
            try:
                stopped, candidate = store.status()
                stop_ok = attempted and confirmed and stopped == "stopped" and monotonic() < cleanup
                if disposition == "candidate-held" and candidate != "captured":
                    disposition = "held"
            except (Hold, OSError, KeyboardInterrupt):
                stop_ok = False
        elif stop_ok:
            terminal = confirmed and monotonic() < cleanup
            try:
                store.finish_cleanup(confirmed=terminal)
                stopped, candidate = store.status()
                stop_ok = terminal and stopped == "stopped" and monotonic() < cleanup
                if disposition == "candidate-held" and candidate != "captured":
                    disposition = "held"
            except (Hold, OSError, KeyboardInterrupt):
                stop_ok = False
        if not stop_ok:
            disposition = "cleanup-unknown"
    return disposition
