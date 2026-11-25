"""Fixed independent capture coordinator protocol and standalone ownership lane."""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from threading import Event, Thread
from typing import Protocol

from t02_capture_bootstrap import InheritedCapture
from t02_capture_evidence import CaptureEvidence
from t02_capture_handoff import (
    StoreIdentity,
    read_handoff,
    store_identity,
    write_handoff,
)
from t02_capture_packet import MAX_PACKET_BYTES, CapturePacket
from t02_capture_private_channel import OwnedPipe
from t02_event_capture import CaptureBinding, CaptureStore
from t02_event_types import Hold, decode, encode

_MAX = MAX_PACKET_BYTES * 2 + 1024
_OFFER = b"lighthouse-capture-coordinator-offer-v1\0"
_RECEIPT = b"lighthouse-capture-coordinator-final-v1\0"
_OUTCOMES = {"candidate-held", "held", "cleanup-unknown"}


def _seal(binding: InheritedCapture, domain: bytes, record: dict[str, object]) -> bytes:
    body = encode(record)
    tag = hmac.new(bytes.fromhex(binding.peer.correlation), domain + body, hashlib.sha256).hexdigest()
    return encode({"body": body.decode("ascii"), "mac": tag})


def _open(binding: InheritedCapture, domain: bytes, wire: bytes) -> dict[str, object]:
    envelope = decode(wire, _MAX)
    raw, mac = envelope.get("body"), envelope.get("mac")
    if (envelope.keys() != {"body", "mac"} or not isinstance(raw, str) or not raw.isascii()
        or not isinstance(mac, str) or not mac.isascii() or len(mac) != 64):
        raise Hold("capture coordinator envelope held")
    body = raw.encode("ascii")
    expected = hmac.new(bytes.fromhex(binding.peer.correlation), domain + body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(mac, expected):
        raise Hold("capture coordinator authentication held")
    return decode(body, _MAX)


def make_offer(
    binding: InheritedCapture, packet: CapturePacket, refs: tuple[int, int], store: CaptureStore,
) -> bytes:
    """The controller may name only exact operation data, never native Job targets."""
    if (store.status()[0] != "claimed" or not store.matches_operation(
        packet.approval.head, packet.approval.digest, packet.approval.activation_ms, packet.intake_cutoff_ms,
    ) or not 0 < refs[0] < refs[1] < 2**63):
        raise Hold("capture coordinator offer held")
    identity = store_identity(store.path)
    return _seal(binding, _OFFER, {
        "packet": packet.canonical.hex(), "refs": refs, "dev": identity.device, "ino": identity.inode,
        "intake": binding.peer.intake_ms, "cleanup": binding.peer.cleanup_ms,
    })


@dataclass(frozen=True, repr=False)
class CoordinatorRun:
    """One exact claim, opened only after the child's independent checks."""

    descriptor: InheritedCapture
    packet: CapturePacket
    refs: tuple[int, int]
    store: CaptureStore
    identity: StoreIdentity


def accept_offer(
    descriptor: InheritedCapture, wire: bytes, mono: Callable[[], int], wall: Callable[[], int],
    evidence: CaptureEvidence, local: Callable[[CapturePacket, int], bool],
) -> CoordinatorRun:
    """Validate fixed source and local facts before any private persistence."""
    body = _open(descriptor, _OFFER, wire)
    raw, refs = body.get("packet"), body.get("refs")
    device, inode = body.get("dev"), body.get("ino")
    if (body.keys() != {"packet", "refs", "dev", "ino", "intake", "cleanup"}
        or not isinstance(raw, str) or not 0 < len(raw) <= 2 * MAX_PACKET_BYTES
        or not isinstance(refs, list) or len(refs) != 2
        or type(refs[0]) is not int or type(refs[1]) is not int or not 0 < refs[0] < refs[1] < 2**63
        or type(device) is not int or type(inode) is not int or inode <= 0
        or body["intake"] != descriptor.peer.intake_ms or body["cleanup"] != descriptor.peer.cleanup_ms):
        raise Hold("capture coordinator fields held")
    try:
        packet = CapturePacket.parse(bytes.fromhex(raw))
    except ValueError:
        raise Hold("capture coordinator packet held") from None
    if (not descriptor.verifies_packet_window(packet, mono, wall)
        or not evidence.allows(packet.approval, refs[0], refs[1],
                               before_ms=descriptor.approval_deadline(packet, mono, wall))
        or not descriptor.verifies_packet_window(packet, mono, wall)
        or not local(packet, descriptor.peer.intake_ms)
        or not descriptor.verifies_packet_window(packet, mono, wall)):
        raise Hold("capture coordinator authority held")
    field = decode(packet.canonical, MAX_PACKET_BYTES)["state"]
    assert isinstance(field, str)
    path = Path(field)
    identity = StoreIdentity(device, inode)
    if str(path.resolve(strict=True)) != field or store_identity(path) != identity:
        raise Hold("capture coordinator store changed")
    target = packet.approval
    state = CaptureStore(path, CaptureBinding(target.head, packet.proof_id, packet.principal,
                                             target.activation_ms, packet.intake_cutoff_ms),
                         operation_digest=target.digest)
    if (state.status()[0] != "claimed" or store_identity(path) != identity
        or not descriptor.verifies_packet_window(packet, mono, wall)):
        raise Hold("capture coordinator claim held")
    state.reserve_coordinator(wall)
    if store_identity(path) != identity or not descriptor.verifies_packet_window(packet, mono, wall):
        raise Hold("capture coordinator admission unknown")
    return CoordinatorRun(descriptor, packet, (refs[0], refs[1]), state, identity)


class FixedProcessLane(Protocol):
    """The independent helper owns fresh Jobs; no launch/kill targets are accepted as input."""

    def arm_local_originals(self) -> None: ...
    def run_fixed(self) -> str: ...
    def stop_at_cutoff(self) -> None: ...


def detached_drive(
    run: CoordinatorRun, make_lane: Callable[[CoordinatorRun], FixedProcessLane],
    mono: Callable[[], int], wait: Callable[[Event, int], bool],
    start: Callable[[Callable[[], None]], None],
) -> str:
    """Observe deadline in the coordinator process, not the blocked role spawn lane."""
    binding = run.descriptor.peer
    if mono() >= binding.intake_ms:
        return "cleanup-unknown"
    lane = make_lane(run)
    lane.arm_local_originals()
    if mono() >= binding.intake_ms:
        lane.stop_at_cutoff()
        return "cleanup-unknown"
    complete = Event()
    result: list[str] = []

    def role_lane() -> None:
        try:
            result.append(lane.run_fixed())
        except (Hold, OSError, KeyboardInterrupt):
            result.append("cleanup-unknown")
        finally:
            complete.set()

    start(role_lane)
    wait(complete, binding.intake_ms)
    if not complete.is_set():
        lane.stop_at_cutoff()
        return "cleanup-unknown"
    if store_identity(run.store.path) != run.identity:
        return "cleanup-unknown"
    final, candidate = run.store.status()
    if store_identity(run.store.path) != run.identity:
        return "cleanup-unknown"
    outcome = result[0] if result else "cleanup-unknown"
    if (mono() >= binding.cleanup_ms or final != "stopped" or outcome not in _OUTCOMES
        or (outcome == "candidate-held" and candidate != "captured")):
        return "cleanup-unknown"
    return outcome


def start_role_lane(run: Callable[[], None]) -> None:
    """Only used inside the separate coordinator executable, never as parent fallback."""
    Thread(target=run, daemon=True, name="fixed-capture-launch").start()


def run_coordinator(
    descriptor: InheritedCapture, pipe: OwnedPipe, mono: Callable[[], int], wall: Callable[[], int],
    evidence: CaptureEvidence, local: Callable[[CapturePacket, int], bool],
    make_lane: Callable[[CoordinatorRun], FixedProcessLane], wait: Callable[[Event, int], bool],
    start: Callable[[Callable[[], None]], None],
) -> str:
    """Consume one offer and send one authenticated allowlisted outcome."""
    wire = read_handoff(pipe, descriptor.peer.intake_ms, mono)
    run = accept_offer(descriptor, wire, mono, wall, evidence, local)
    disposition = detached_drive(run, make_lane, mono, wait, start)
    if mono() < descriptor.peer.cleanup_ms:
        write_handoff(pipe, make_receipt(descriptor, disposition), descriptor.peer.cleanup_ms)
    return disposition


def make_receipt(descriptor: InheritedCapture, disposition: str) -> bytes:
    if disposition not in _OUTCOMES:
        raise Hold("capture coordinator outcome held")
    return _seal(descriptor, _RECEIPT, {
        "head": descriptor.head, "digest": descriptor.packet_digest,
        "intake": descriptor.peer.intake_ms, "cleanup": descriptor.peer.cleanup_ms,
        "outcome": disposition,
    })


def verify_receipt(descriptor: InheritedCapture, wire: bytes, store: CaptureStore) -> str:
    """An authenticated claim is not a success without the same durable terminal record."""
    fields = _open(descriptor, _RECEIPT, wire)
    outcome = fields.get("outcome")
    if (fields.keys() != {"head", "digest", "intake", "cleanup", "outcome"}
        or fields["head"] != descriptor.head or fields["digest"] != descriptor.packet_digest
        or fields["intake"] != descriptor.peer.intake_ms or fields["cleanup"] != descriptor.peer.cleanup_ms
        or not isinstance(outcome, str) or outcome not in _OUTCOMES):
        raise Hold("capture coordinator final receipt held")
    if outcome == "cleanup-unknown":
        return outcome
    stage, disposition = store.status()
    if stage != "stopped" or (outcome == "candidate-held" and disposition != "captured"):
        return "cleanup-unknown"
    return outcome
