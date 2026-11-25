"""Claim-bound private packet/Job transfer for one fixed capture supervisor."""

from __future__ import annotations

import hashlib
import hmac
import struct
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from t02_capture_bootstrap import InheritedCapture
from t02_capture_evidence import CaptureEvidence
from t02_capture_packet import MAX_PACKET_BYTES, CapturePacket
from t02_capture_private_channel import OwnedPipe
from t02_event_capture import CaptureBinding, CaptureStore
from t02_event_types import Hold, decode, encode

_MAX_HANDOFF = MAX_PACKET_BYTES * 2 + 1024
_DOMAIN = b"lighthouse-capture-handoff-v1\0"


@dataclass(frozen=True, repr=False)
class StoreIdentity:
    device: int
    inode: int


@dataclass(frozen=True, repr=False)
class AcceptedHandoff:
    packet: CapturePacket
    store: CaptureStore
    jobs: tuple[int, int]
    approval_refs: tuple[int, int]


def store_identity(path: Path) -> StoreIdentity:
    """Identify the exact existing SQLite owner, never create a DB here."""
    info = path.stat()
    if info.st_ino <= 0:
        raise Hold("capture DB identity unavailable")
    return StoreIdentity(info.st_dev, info.st_ino)


def _mac(descriptor: InheritedCapture, body: bytes) -> str:
    return hmac.new(bytes.fromhex(descriptor.peer.correlation), _DOMAIN + body, hashlib.sha256).hexdigest()


def make_handoff(
    descriptor: InheritedCapture,
    packet: CapturePacket,
    store: CaptureStore,
    jobs: tuple[int, int],
    mono: Callable[[], int],
    wall: Callable[[], int],
    *, approval_refs: tuple[int, int], identify: Callable[[Path], StoreIdentity] = store_identity,
) -> bytes:
    """Send the canonical packet and exact already-admitted DB identity once."""
    if (not descriptor.verifies_packet_window(packet, mono, wall)
        or not store.matches_operation(packet.approval.head, packet.approval.digest,
                                       packet.approval.activation_ms, packet.intake_cutoff_ms)
        or store.binding.proof_id != packet.proof_id or store.binding.principal != packet.principal
        or not _valid_refs(approval_refs) or not _valid_jobs(descriptor, jobs) or store.status()[0] != "claimed"):
        raise Hold("capture packet handoff unavailable")
    paths = decode(packet.canonical, MAX_PACKET_BYTES)
    if str(store.path) != paths["state"]:
        raise Hold("capture DB path mismatch")
    identity = identify(store.path)
    if mono() >= descriptor.peer.intake_ms:
        raise Hold("capture packet handoff expired")
    message = encode({
        "packet": packet.canonical.hex(), "jobs": jobs, "device": identity.device, "inode": identity.inode,
        "approvals": approval_refs,
        "intake": descriptor.peer.intake_ms, "cleanup": descriptor.peer.cleanup_ms,
    })
    return encode({"body": message.decode("ascii"), "mac": _mac(descriptor, message)})


def _valid_refs(refs: tuple[int, int]) -> bool:
    return type(refs[0]) is int and type(refs[1]) is int and 0 < refs[0] < refs[1] < 2**63


def _valid_jobs(descriptor: InheritedCapture, jobs: tuple[int, int]) -> bool:
    return (
        len(jobs) == 2 and all(type(job) is int and 0 < job < 2**63 for job in jobs)
        and jobs[0] != jobs[1] and not set(jobs).intersection(descriptor.peer.handles)
    )


def receive_handoff(
    descriptor: InheritedCapture,
    wire: bytes,
    mono: Callable[[], int],
    wall: Callable[[], int],
    owns_exact_jobs: Callable[[tuple[int, int]], bool],
    *, evidence: CaptureEvidence, identify: Callable[[Path], StoreIdentity] = store_identity,
) -> AcceptedHandoff:
    """Authenticate packet before opening local state or inspecting either role Job."""
    envelope = decode(wire, _MAX_HANDOFF)
    raw, signature = envelope.get("body"), envelope.get("mac")
    if (envelope.keys() != {"body", "mac"} or not isinstance(raw, str) or not raw.isascii()
        or not isinstance(signature, str) or not signature.isascii() or len(signature) != 64
        or not hmac.compare_digest(signature, _mac(descriptor, raw.encode("ascii")))):
        raise Hold("capture handoff authentication failed")
    body = decode(raw.encode("ascii"), _MAX_HANDOFF)
    packet_bytes, jobs = body.get("packet"), body.get("jobs")
    device, inode = body.get("device"), body.get("inode")
    refs = body.get("approvals")
    if (body.keys() != {"packet", "jobs", "device", "inode", "intake", "cleanup", "approvals"}
        or not isinstance(packet_bytes, str) or not isinstance(jobs, list) or len(jobs) != 2
        or not isinstance(refs, list) or len(refs) != 2 or not _valid_refs((refs[0], refs[1]))
        or type(jobs[0]) is not int or type(jobs[1]) is not int or type(device) is not int
        or type(inode) is not int or inode <= 0 or body["intake"] != descriptor.peer.intake_ms
        or body["cleanup"] != descriptor.peer.cleanup_ms):
        raise Hold("invalid capture handoff fields")
    role_jobs = jobs[0], jobs[1]
    try:
        packet = CapturePacket.parse(bytes.fromhex(packet_bytes))
    except ValueError:
        raise Hold("capture handoff packet malformed") from None
    if (not descriptor.verifies_packet_window(packet, mono, wall) or not _valid_jobs(descriptor, role_jobs)
        or not owns_exact_jobs(role_jobs) or mono() >= descriptor.peer.intake_ms):
        raise Hold("capture role handoff held")
    if (not evidence.allows(packet.approval, refs[0], refs[1],
                            before_ms=descriptor.approval_deadline(packet, mono, wall))
        or not descriptor.verifies_packet_window(packet, mono, wall)):
        raise Hold("capture child authority held")
    fields = decode(packet.canonical, MAX_PACKET_BYTES)
    raw_path = fields["state"]
    assert isinstance(raw_path, str)
    path = Path(raw_path)
    expected = StoreIdentity(device, inode)
    if str(path.resolve(strict=True)) != raw_path or identify(path) != expected:
        raise Hold("capture DB identity differs")
    binding = CaptureBinding(packet.approval.head, packet.proof_id, packet.principal,
                             packet.approval.activation_ms, packet.intake_cutoff_ms)
    store = CaptureStore(path, binding, operation_digest=packet.approval.digest)
    if store.status()[0] != "claimed" or identify(path) != expected or mono() >= descriptor.peer.intake_ms:
        raise Hold("capture DB changed or not admitted")
    store.reserve_handoff(wall)
    if identify(path) != expected or mono() >= descriptor.peer.intake_ms:
        raise Hold("capture handoff confirmation unknown")
    return AcceptedHandoff(packet, store, role_jobs, (refs[0], refs[1]))


def write_handoff(pipe: OwnedPipe, body: bytes, deadline: int) -> None:
    """Send one bounded packet before normal role-control frames."""
    if not 0 < len(body) <= _MAX_HANDOFF:
        raise Hold("capture handoff length held")
    pipe.write(struct.pack("<I", len(body)), deadline)
    for start in range(0, len(body), 1024):
        pipe.write(body[start:start + 1024], deadline)


def read_handoff(pipe: OwnedPipe, deadline: int, mono: Callable[[], int]) -> bytes:
    """Read only the one bootstrap envelope, without retrying an unknown frame."""
    def get(count: int) -> bytes:
        result = bytearray()
        while len(result) < count and mono() < deadline:
            request = min(count - len(result), 1024)
            chunk = pipe.read(request, deadline)
            if not chunk or len(chunk) > request:
                break
            result.extend(chunk)
        if len(result) != count or mono() >= deadline:
            raise Hold("capture handoff read held")
        return bytes(result)

    size, = struct.unpack("<I", get(4))
    if not 0 < size <= _MAX_HANDOFF:
        raise Hold("capture handoff length held")
    return get(size)
