"""Internal fixed helper composition behind the disabled operator entry."""

from collections.abc import Callable

from t02_capture_bootstrap import InheritedCapture
from t02_capture_native_peer import run_native_peer
from t02_capture_packet import CapturePacket
from t02_capture_supervisor import CaptureSupervisor, HostedRole, HostStatus
from t02_capture_terminal import CaptureTerminalOwner
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
    if (descriptor.head != target.head or descriptor.packet_digest != target.digest
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
