"""Exact capture-only listener and pinned vendor role selection."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from t02_capture_local import LocalCaptureObservation, matches_local_capture
from t02_capture_packet import MAX_PACKET_BYTES, CapturePacket
from t02_event_capture import CaptureStore, capture_receiver
from t02_event_loopback import LoopbackRole
from t02_event_types import Hold, decode
from t02_event_windows import RuntimeRole


@dataclass(frozen=True, repr=False)
class _RuntimeBinding:
    tunnel: str
    platform: str
    runtime_binary_digest: str


def fixed_capture_runtime(
    packet: CapturePacket, local: LocalCaptureObservation, bearer: str, key: str,
    clock: Callable[[], int],
) -> RuntimeRole:
    """Select only the attested pinned role using creation-time Job assignment."""
    if not matches_local_capture(packet, local):
        raise Hold("capture runtime local identity unavailable")
    record = decode(packet.canonical, MAX_PACKET_BYTES)
    tunnel, org, digest, executable = (record[name] for name in (
        "tunnel", "organization", "runtime_executable_sha256", "runtime_executable",
    ))
    if not all(isinstance(part, str) for part in (tunnel, org, digest, executable)):
        raise Hold("capture runtime identity unavailable")
    assert isinstance(tunnel, str) and isinstance(org, str)
    assert isinstance(digest, str) and isinstance(executable, str)
    return RuntimeRole(Path(executable), _RuntimeBinding(tunnel, org, digest), bearer, key, clock, atomic_job=True)


def fixed_capture_listener(
    store: CaptureStore, bearer: str, clock: Callable[[], int], *, rpc_clock: Callable[[], int] | None = None,
) -> LoopbackRole:
    """Select the capture receiver, never an outbound callback sender.

    The caller must be the isolated listener helper; this factory does not
    launch a helper or grant listen authority.
    """
    receiver = capture_receiver(store.binding, store, bearer, rpc_clock if rpc_clock is not None else clock)
    return LoopbackRole("127.0.0.1", 8765, receiver, clock)
