"""Fixed capture controller composition; release stays separately fail-closed."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from t02_capture_evidence import CaptureEvidence
from t02_capture_lifecycle import CaptureRoles, guarded_capture
from t02_capture_local import LocalCaptureObservation, matches_local_capture
from t02_capture_packet import MAX_PACKET_BYTES, CapturePacket
from t02_event_capture import CaptureBinding, CaptureStore
from t02_event_types import Hold, decode


@dataclass(frozen=True)
class CaptureWindow:
    """The monotonic translation from the original approved wall deadlines."""

    intake: int
    cleanup: int

    @classmethod
    def from_packet(cls, packet: CapturePacket, wall: Callable[[], int], mono: Callable[[], int]) -> CaptureWindow:
        tick, sampled_wall = mono(), wall()
        return cls(tick + packet.intake_cutoff_ms - sampled_wall,
                   tick + packet.approval.cutoff_ms - sampled_wall)


@dataclass(frozen=True)
class SelectedCapture:
    """Internal I/O boundaries for offline proof; none is selectable through arguments."""

    wall: Callable[[], int]
    mono: Callable[[], int]
    evidence: CaptureEvidence
    observe: Callable[[CapturePacket, int], LocalCaptureObservation]
    connect: Callable[[CapturePacket, CaptureStore, CaptureWindow, tuple[int, int]], CaptureRoles]


def open_existing_capture(packet: CapturePacket) -> CaptureStore:
    """Use only the packet's exact store under the operation binding."""
    record = decode(packet.canonical, MAX_PACKET_BYTES)
    path = record["state"]
    assert isinstance(path, str)
    binding = CaptureBinding(packet.approval.head, packet.proof_id, packet.principal,
                             packet.approval.activation_ms, packet.intake_cutoff_ms)
    store = CaptureStore(Path(path), binding, operation_digest=packet.approval.digest)
    if str(store.path) != path:
        raise Hold("capture store path held")
    return store


class _LazyOwner:
    """Do not construct any process/pipe effect factory before committed admission."""

    def __init__(self, connect: Callable[[], CaptureRoles]) -> None:
        self._connect = connect
        self._owner: CaptureRoles | None = None
        self._attempted = False

    def arm(self, cleanup_deadline_ms: int) -> None:
        if self._attempted:
            raise Hold("capture owner will not retry")
        self._attempted = True
        self._owner = self._connect()
        self._owner.arm(cleanup_deadline_ms)

    def _exact_owner(self) -> CaptureRoles:
        if self._owner is None:
            raise Hold("capture owner unknown")
        return self._owner

    def start_listener(self, intake_deadline_ms: int) -> None:
        self._exact_owner().start_listener(intake_deadline_ms)

    def start_runtime(self, intake_deadline_ms: int) -> None:
        self._exact_owner().start_runtime(intake_deadline_ms)

    def wait_candidate(self, intake_deadline_ms: int) -> None:
        self._exact_owner().wait_candidate(intake_deadline_ms)

    def signal_all(self) -> None:
        self._exact_owner().signal_all()

    def confirmed_stopped(self, cleanup_deadline_ms: int) -> bool:
        return self._exact_owner().confirmed_stopped(cleanup_deadline_ms)


def run_selected_capture(
    packet: CapturePacket, owner_ref: int, lead_ref: int, selected: SelectedCapture,
) -> str:
    """Apply current authority before local I/O and pass one fixed window into the owner."""
    window = CaptureWindow.from_packet(packet, selected.wall, selected.mono)
    if not selected.mono() < window.intake < window.cleanup:
        return "denied"
    target = packet.approval
    if not selected.evidence.allows(target, owner_ref, lead_ref, before_ms=packet.intake_cutoff_ms):
        return "denied"
    try:
        observation = selected.observe(packet, window.intake)
        if selected.mono() >= window.intake or not matches_local_capture(packet, observation):
            return "denied"
        if not selected.evidence.allows(target, owner_ref, lead_ref, before_ms=packet.intake_cutoff_ms):
            return "denied"
        if selected.mono() >= window.intake:
            return "denied"
        store = open_existing_capture(packet)
    except (Hold, OSError, ValueError, KeyboardInterrupt):
        return "denied"
    roles = _LazyOwner(lambda: selected.connect(packet, store, window, (owner_ref, lead_ref)))
    return guarded_capture(
        packet, store, selected.evidence, owner_ref, lead_ref, selected.wall, selected.mono,
        lambda: observation, roles, supervisor_finalizes=True, original_window=(window.intake, window.cleanup),
    )


def released() -> bool:
    """No caller input can install the reviewed native execution binding."""
    from t02_capture_native_composition import released_capture

    return released_capture() is not None


def execute_capture(packet: CapturePacket, owner_ref: int, lead_ref: int) -> str:
    """Enter the fixed mapping only when the exact installation is released."""
    from t02_capture_native_composition import launch_coordinator, released_capture

    binding = released_capture()
    if binding is None:
        return "denied"
    return launch_coordinator(binding, packet, (owner_ref, lead_ref))


def run_native_listener_entry() -> int:
    """Select only the installed listener dispatcher; no environment enables it."""
    from t02_capture_native_composition import released_capture

    binding = released_capture("listener")
    if binding is None or binding.native is None:
        return 2
    from t02_capture_local import matches_local_capture

    return binding.native.listener_dispatch(
        lambda packet, deadline: matches_local_capture(packet, binding.host.observe(packet, deadline)),
    )


def run_native_supervisor_entry() -> int:
    """Select the fixed supervisor dispatcher only from the installed binding."""
    from t02_capture_native_composition import released_capture, start_supervisor

    binding = released_capture("supervisor")
    return 2 if binding is None else start_supervisor(binding)
