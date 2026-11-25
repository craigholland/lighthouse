"""Fixed listener-helper lifecycle; direct invocation remains disabled."""

from __future__ import annotations

import hashlib
import hmac
import re
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from t02_capture_bootstrap import InheritedCapture
    from t02_capture_evidence import CaptureEvidence
    from t02_capture_handoff import AcceptedHandoff, StoreIdentity
    from t02_capture_packet import CapturePacket
    from t02_capture_private_channel import OwnedPipe
    from t02_event_capture import CaptureStore


def listen_bound(
    descriptor: InheritedCapture,
    packet: CapturePacket,
    store: CaptureStore,
    load_bearer: Callable[[], str],
    wait_stop: Callable[[int, int], bool],
    mono: Callable[[], int],
    wall: Callable[[], int],
    *, on_ready: Callable[[], None] = lambda: None,
) -> str:
    """Run the one fixed listener only after exact operation and intake checks."""
    from t02_capture_roles import fixed_capture_listener
    from t02_event_types import Hold

    target = packet.approval
    deadline, cleanup = descriptor.peer.intake_ms, descriptor.peer.cleanup_ms
    if (not descriptor.verifies_packet_window(packet, mono, wall)
        or not store.matches_operation(target.head, target.digest, target.activation_ms, packet.intake_cutoff_ms)
        or store.binding.principal != packet.principal or store.binding.proof_id != packet.proof_id
        or not target.activation_ms <= wall() < packet.intake_cutoff_ms
        or mono() >= deadline or store.status()[0] != "claimed"):
        raise Hold("capture listener handoff unavailable")
    bearer = load_bearer()
    if (
        not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", bearer)
        or not descriptor.verifies_packet_window(packet, mono, wall)
        or store.status()[0] != "claimed"
    ):
        raise Hold("capture listener private input held")

    def intake_wall() -> int:
        return max(wall(), packet.intake_cutoff_ms) if mono() >= deadline else wall()

    role = fixed_capture_listener(store, bearer, mono, rpc_clock=intake_wall)
    startup = False
    quiescent = False
    try:
        startup = mono() < deadline and role.start(deadline)
        if startup and mono() < deadline:
            on_ready()
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


_DOMAIN = b"lighthouse-capture-listener-handoff-v1\0"
_READY_DOMAIN = b"lighthouse-capture-listener-ready-v1\0"
_MAX_WIRE = 19_000


def _signed(descriptor: InheritedCapture, domain: bytes, body: bytes) -> str:
    return hmac.new(bytes.fromhex(descriptor.peer.correlation), domain + body, hashlib.sha256).hexdigest()


def make_listener_handoff(
    descriptor: InheritedCapture, accepted: AcceptedHandoff, mono: Callable[[], int],
    wall: Callable[[], int], identify: Callable[[Path], StoreIdentity],
) -> bytes:
    """Bind an admitted operation to one distinct listener endpoint; no secret data."""
    from t02_event_types import Hold, encode

    if not descriptor.verifies_packet_window(accepted.packet, mono, wall):
        raise Hold("capture listener handoff held")
    identity = identify(accepted.store.path)
    if identity.inode <= 0 or accepted.store.status()[0] != "claimed" or mono() >= descriptor.peer.intake_ms:
        raise Hold("capture listener store unavailable")
    body = encode({
        "packet": accepted.packet.canonical.hex(), "refs": accepted.approval_refs,
        "device": identity.device, "inode": identity.inode,
        "intake": descriptor.peer.intake_ms, "cleanup": descriptor.peer.cleanup_ms,
    })
    return encode({"body": body.decode("ascii"), "mac": _signed(descriptor, _DOMAIN, body)})


def listener_ready_receipt(descriptor: InheritedCapture) -> bytes:
    """Authenticate a fixed readiness response, not a stop/terminal witness."""
    return _signed(descriptor, _READY_DOMAIN, descriptor.packet_digest.encode("ascii")).encode("ascii")


def run_transferred_listener(
    raw_descriptor: str,
    mono: Callable[[], int],
    wall: Callable[[], int],
    owns_pipe: Callable[[int], bool],
    owns_stop: Callable[[int], bool],
    open_pipe: Callable[[tuple[int, int, int]], OwnedPipe],
    wait_stop: Callable[[int, int], bool],
    evidence: CaptureEvidence,
    *, released: Callable[[], bool],
) -> str:
    """Admit independently validated child capabilities and source approvals before I/O."""
    from t02_capture_bootstrap import InheritedCapture
    from t02_capture_handoff import (
        StoreIdentity,
        read_handoff,
        store_identity,
        write_handoff,
    )
    from t02_capture_local_windows import _canonical
    from t02_capture_packet import MAX_PACKET_BYTES, CapturePacket
    from t02_capture_roles import _read_capture_secret
    from t02_event_capture import CaptureBinding, CaptureStore
    from t02_event_types import Hold, decode

    if not released():
        raise Hold("capture listener release unavailable")
    descriptor = InheritedCapture.accept(raw_descriptor, mono, owns_pipe, owns_stop)
    deadline = descriptor.peer.intake_ms
    pipe = open_pipe(descriptor.peer.handles)
    envelope = decode(read_handoff(pipe, deadline, mono), _MAX_WIRE)
    raw, mac = envelope.get("body"), envelope.get("mac")
    if (
        envelope.keys() != {"body", "mac"} or not isinstance(raw, str) or not raw.isascii()
        or not isinstance(mac, str) or not re.fullmatch(r"[0-9a-f]{64}", mac)
        or not hmac.compare_digest(mac, _signed(descriptor, _DOMAIN, raw.encode("ascii")))
    ):
        raise Hold("capture listener handoff authentication failed")
    body = decode(raw.encode("ascii"), _MAX_WIRE)
    packet_hex, refs = body.get("packet"), body.get("refs")
    device, inode = body.get("device"), body.get("inode")
    if (
        body.keys() != {"packet", "refs", "device", "inode", "intake", "cleanup"}
        or type(body["intake"]) is not int or body["intake"] != deadline
        or type(body["cleanup"]) is not int or body["cleanup"] != descriptor.peer.cleanup_ms
        or not isinstance(packet_hex, str) or not 0 < len(packet_hex) <= 2 * MAX_PACKET_BYTES
        or not re.fullmatch(r"[0-9a-f]+", packet_hex) or len(packet_hex) % 2
        or not isinstance(refs, list) or len(refs) != 2
        or type(refs[0]) is not int or type(refs[1]) is not int or not 0 < refs[0] < refs[1] < 2**63
        or type(device) is not int or type(inode) is not int or inode <= 0
    ):
        raise Hold("capture listener handoff fields held")
    packet = CapturePacket.parse(bytes.fromhex(packet_hex))
    if (
        not descriptor.verifies_packet_window(packet, mono, wall)
        or not evidence.allows(packet.approval, refs[0], refs[1],
                               before_ms=descriptor.approval_deadline(packet, mono, wall))
        or not descriptor.verifies_packet_window(packet, mono, wall)
    ):
        raise Hold("capture listener authority held")
    record = decode(packet.canonical, MAX_PACKET_BYTES)
    raw_path = record["state"]
    assert isinstance(raw_path, str)
    target = packet.approval
    path = Path(raw_path)
    expected = StoreIdentity(device, inode)
    try:
        if _canonical(path, directory=False) != raw_path or store_identity(path) != expected:
            raise Hold("capture listener store identity held")
        binding = CaptureBinding(target.head, packet.proof_id, packet.principal,
                                 target.activation_ms, packet.intake_cutoff_ms)
        store = CaptureStore(path, binding, operation_digest=target.digest)
        if store.status()[0] != "claimed" or store_identity(path) != expected:
            raise Hold("capture listener store identity held")
    except OSError:
        raise Hold("capture listener store unavailable") from None

    return listen_bound(
        descriptor, packet, store,
        lambda: _read_capture_secret(packet, "loopback_bearer", mono, deadline),
        wait_stop, mono, wall,
        on_ready=lambda: write_handoff(pipe, listener_ready_receipt(descriptor), deadline),
    )


def main() -> int:
    """Enter only the fixed composition; a source-defined release gate still holds."""
    from t02_capture_composition import run_native_listener_entry

    return run_native_listener_entry()


if __name__ == "__main__":
    import sys

    # The host launches the fixed -I script, never a module from an ambient path.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    raise SystemExit(main())
