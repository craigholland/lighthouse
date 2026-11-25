"""Internal fixed helper composition behind the disabled operator entry."""

from collections.abc import Callable

from t02_capture_bootstrap import InheritedCapture
from t02_capture_handoff import AcceptedHandoff, read_handoff, receive_handoff
from t02_capture_native_peer import run_native_peer
from t02_capture_packet import CapturePacket
from t02_capture_supervisor import CaptureSupervisor, HostedRole, HostStatus
from t02_capture_terminal import CaptureTerminalOwner
from t02_capture_windows_pipe import WindowsCapturePipe
from t02_event_capture import CaptureStore
from t02_event_types import Hold


def run_inherited_supervisor(
    raw_descriptor: str,
    packet: CapturePacket,
    store: CaptureStore,
    mono: Callable[[], int],
    wall: Callable[[], int],
    owns_pipe: Callable[[int], bool],
    owns_stop: Callable[[int], bool],
    listener_factory: Callable[[], HostedRole],
    runtime_factory: Callable[[], HostedRole],
) -> HostStatus:
    """Build the dormant native peer only for an already-claimed exact run."""
    descriptor = InheritedCapture.accept(raw_descriptor, mono, owns_pipe, owns_stop)
    target = packet.approval
    if (not descriptor.verifies_packet_window(packet, mono, wall)
        or not store.matches_operation(target.head, target.digest, target.activation_ms, packet.intake_cutoff_ms)
        or store.binding.proof_id != packet.proof_id or store.binding.principal != packet.principal
        or not target.activation_ms <= wall() < packet.intake_cutoff_ms
        or store.status()[0] != "claimed" or mono() >= descriptor.peer.intake_ms):
        raise Hold("capture supervisor handoff unavailable")
    listener = listener_factory()
    if mono() >= descriptor.peer.intake_ms:
        raise Hold("capture supervisor handoff expired")
    runtime = runtime_factory()
    host = CaptureSupervisor(
        mono, descriptor.peer.intake_ms, descriptor.peer.cleanup_ms,
        listener, runtime, CaptureTerminalOwner(store),
    )
    return run_native_peer(descriptor.peer, host, mono)


def run_transferred_supervisor(
    raw_descriptor: str,
    mono: Callable[[], int],
    wall: Callable[[], int],
    owns_pipe: Callable[[int], bool],
    owns_stop: Callable[[int], bool],
    owns_exact_jobs: Callable[[tuple[int, int]], bool],
    listener_factory: Callable[[AcceptedHandoff, int], HostedRole],
    runtime_factory: Callable[[AcceptedHandoff, int], HostedRole],
) -> HostStatus:
    """Read the authenticated inherited channel; admit both Jobs before role effects.

    This topology leaves terminal writing with the detached owner, not the
    listener or controller. Direct helper and public activation remain denied.
    """
    descriptor = InheritedCapture.accept(raw_descriptor, mono, owns_pipe, owns_stop)
    pipe = WindowsCapturePipe(*descriptor.peer.handles, mono)
    wire = read_handoff(pipe, descriptor.peer.intake_ms, mono)
    accepted = receive_handoff(descriptor, wire, mono, wall, owns_exact_jobs)
    if not descriptor.verifies_packet_window(accepted.packet, mono, wall):
        raise Hold("capture owner handoff expired")
    listener = listener_factory(accepted, accepted.jobs[0])
    if not descriptor.verifies_packet_window(accepted.packet, mono, wall):
        raise Hold("capture listener construction crossed cutoff")
    runtime = runtime_factory(accepted, accepted.jobs[1])
    host = CaptureSupervisor(
        mono, descriptor.peer.intake_ms, descriptor.peer.cleanup_ms,
        listener, runtime, CaptureTerminalOwner(accepted.store),
    )
    return run_native_peer(descriptor.peer, host, mono)
