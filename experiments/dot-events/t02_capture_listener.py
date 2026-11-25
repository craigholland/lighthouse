"""Fixed listener-helper lifecycle; direct invocation remains disabled."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from t02_capture_bootstrap import InheritedCapture
    from t02_capture_packet import CapturePacket
    from t02_event_capture import CaptureStore


def listen_bound(
    descriptor: InheritedCapture,
    packet: CapturePacket,
    store: CaptureStore,
    load_bearer: Callable[[], str],
    wait_stop: Callable[[int, int], bool],
    mono: Callable[[], int],
    wall: Callable[[], int],
) -> str:
    """Run the one fixed listener only after exact operation and intake checks."""
    from t02_capture_roles import fixed_capture_listener
    from t02_event_types import Hold

    target = packet.approval
    deadline, cleanup = descriptor.peer.intake_ms, descriptor.peer.cleanup_ms
    if (descriptor.head != target.head or descriptor.packet_digest != target.digest
        or not store.matches_operation(target.head, target.digest, target.activation_ms, packet.intake_cutoff_ms)
        or store.binding.principal != packet.principal or store.binding.proof_id != packet.proof_id
        or not target.activation_ms <= wall() < packet.intake_cutoff_ms
        or mono() >= deadline or store.status()[0] != "claimed"):
        raise Hold("capture listener handoff unavailable")
    bearer = load_bearer()
    if not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", bearer) or mono() >= deadline:
        raise Hold("capture listener private input held")

    def intake_wall() -> int:
        return max(wall(), packet.intake_cutoff_ms) if mono() >= deadline else wall()

    role = fixed_capture_listener(store, bearer, mono, rpc_clock=intake_wall)
    startup = False
    quiescent = False
    try:
        startup = mono() < deadline and role.start(deadline)
        if startup and mono() < deadline:
            wait_stop(descriptor.peer.handles[2], deadline)
    except (Hold, OSError, KeyboardInterrupt):
        startup = False
    finally:
        try:
            role.request_stop(cleanup)
        finally:
            quiescent = role.confirmed_quiescent(cleanup) and mono() < cleanup
    if not quiescent:
        return "cleanup-unknown"
    return "stopped" if startup else "held"


def main() -> int:
    """No public or directly invoked helper activation until native proof."""
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
