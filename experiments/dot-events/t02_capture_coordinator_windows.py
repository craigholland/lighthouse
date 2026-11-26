"""Fixed executable bootstrap for the independently bounded capture owner."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from threading import Event

from t02_capture_bootstrap import InheritedCapture
from t02_capture_coordinator import (
    CoordinatorRun,
    make_offer,
    run_coordinator,
    start_role_lane,
    verify_receipt,
)
from t02_capture_evidence import CaptureEvidence
from t02_capture_handoff import read_handoff, store_identity, write_handoff
from t02_capture_lifecycle import CaptureRoles
from t02_capture_native_cutoff import FixedWindowsCutoff
from t02_capture_packet import CapturePacket
from t02_capture_peer import PeerBinding
from t02_capture_pipe_owner import CapturePipeOwner
from t02_capture_trusted import bound_child_environment
from t02_capture_windows_pipe import WindowsCapturePipe
from t02_event_capture import CaptureStore
from t02_event_types import Hold
from t02_event_windows import _OwnedWindowsJob

_SCRIPT = Path(__file__).with_name("t02_capture_coordinator_entry.py")


class CaptureCoordinatorHost(_OwnedWindowsJob):
    """Launch only the fixed coordinator with only its one IPC capability tuple."""

    def __init__(self, python: Path, mono: Callable[[], int]) -> None:
        if not python.is_absolute() or python.name.casefold() != "python.exe":
            raise Hold("capture coordinator interpreter held")
        super().__init__(mono)
        self._python = python

    def start_bootstrap(self, descriptor: InheritedCapture) -> bool:
        return self._start_owned(
            self._python, ["-I", str(_SCRIPT)], bound_child_environment("coordinator", descriptor), descriptor.peer.intake_ms,
            bind_at_creation=True, inherited=descriptor.peer.handles,
        )


def dispatch_owned(
    packet: CapturePacket, state: CaptureStore, refs: tuple[int, int], intake: int, cleanup: int,
    mono: Callable[[], int], host: CaptureCoordinatorHost, owner: CapturePipeOwner, correlation: str,
) -> str:
    """The controller never owns role Jobs nor attaches a second terminal writer."""
    attempted = False
    try:
        handles = owner.prepare(intake)
        descriptor = InheritedCapture(
            PeerBinding.from_owner(handles, correlation, intake, cleanup), packet.approval.head, packet.approval.digest,
        )
        identity = store_identity(state.path)
        wire = make_offer(descriptor, packet, refs, state)
        if store_identity(state.path) != identity:
            raise Hold("capture coordinator store changed")
        if mono() >= intake:
            raise Hold("capture coordinator start expired")
        attempted = True
        try:
            if not host.start_bootstrap(descriptor):
                raise Hold("capture coordinator startup unknown")
        finally:
            owner.release_supervisor_copies()
        pipe = WindowsCapturePipe(*handles.controller, mono)
        write_handoff(pipe, wire, intake)
        response = read_handoff(pipe, cleanup, mono)
        if store_identity(state.path) != identity:
            raise Hold("capture coordinator receipt store changed")
        outcome = verify_receipt(descriptor, response, state)
        if not host.confirmed_quiescent(cleanup) or store_identity(state.path) != identity:
            return "cleanup-unknown"
        return outcome
    except (Hold, OSError, ValueError, KeyboardInterrupt):
        if attempted:
            host.request_stop(cleanup)
            host.confirmed_quiescent(cleanup)
        return "cleanup-unknown"
    finally:
        owner.close()


class FixedCoordinatorLane:
    """Originals are allocated in this coordinator before the blocking role lane."""

    def __init__(
        self, run: CoordinatorRun, mono: Callable[[], int],
        objects: Callable[[], tuple[FixedWindowsCutoff, CaptureRoles]],
        authorize: Callable[[], bool],
    ) -> None:
        self._run, self._mono, self._objects, self._authorize = run, mono, objects, authorize
        self._fixed: FixedWindowsCutoff | None = None
        self._roles: CaptureRoles | None = None

    def arm_local_originals(self) -> None:
        if self._fixed is not None:
            raise Hold("capture coordinator cannot rearm")
        self._fixed, self._roles = self._objects()

    def run_fixed(self) -> str:
        roles = self._roles
        if roles is None:
            raise Hold("capture coordinator not armed")
        cap = self._run.descriptor.peer
        outcome = "held"
        try:
            if not self._authorize():
                raise Hold("capture coordinator current authority held")
            roles.arm(cap.cleanup_ms)
            if not self._authorize():
                raise Hold("capture coordinator listener authority held")
            roles.start_listener(cap.intake_ms)
            if not self._authorize():
                raise Hold("capture coordinator runtime authority held")
            roles.start_runtime(cap.intake_ms)
            roles.wait_candidate(cap.intake_ms)
            if self._run.store.status() == ("claimed", "captured"):
                outcome = "candidate-held"
        except (Hold, OSError, KeyboardInterrupt):
            outcome = "held"
        finally:
            try:
                roles.signal_all()
                if not roles.confirmed_stopped(cap.cleanup_ms):
                    outcome = "cleanup-unknown"
            except (Hold, OSError, KeyboardInterrupt):
                outcome = "cleanup-unknown"
        return outcome

    def stop_at_cutoff(self) -> None:
        if self._fixed is None:
            raise Hold("capture cutoff owner unavailable")
        try:
            self._fixed.stop_due()
        finally:
            # Missing exact role roots never upgrade the emergency disposition.
            self._run.store.hold_terminal()


def owned_entry(
    descriptor: InheritedCapture, mono: Callable[[], int], wall: Callable[[], int],
    evidence: CaptureEvidence, local: Callable[[CapturePacket, int], bool],
    objects: Callable[[CoordinatorRun], tuple[FixedWindowsCutoff, CaptureRoles]],
) -> str:
    """Run the pipe and deadline watcher inside the separately launched executable."""
    pipe = WindowsCapturePipe(*descriptor.peer.handles, mono)

    def lane(run: CoordinatorRun) -> FixedCoordinatorLane:
        def current() -> bool:
            return (
                descriptor.verifies_packet_window(run.packet, mono, wall)
                and evidence.allows(run.packet.approval, *run.refs,
                                    before_ms=descriptor.approval_deadline(run.packet, mono, wall))
                and descriptor.verifies_packet_window(run.packet, mono, wall)
            )

        return FixedCoordinatorLane(run, mono, lambda: objects(run), current)

    def wait(signal: Event, cutoff: int) -> bool:
        return signal.wait(max(0, cutoff - mono()) / 1000)

    return run_coordinator(descriptor, pipe, mono, wall, evidence, local, lane, wait, start_role_lane)
