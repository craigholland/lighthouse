"""Parent half of the dormant capture handoff from the detached Job owner."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from t02_capture_bootstrap import InheritedCapture
from t02_capture_handoff import make_handoff, write_handoff
from t02_capture_owned_jobs import OwnedCaptureJobs
from t02_capture_packet import CapturePacket
from t02_capture_peer import PeerBinding
from t02_capture_pipe_owner import CapturePipeHandles, CapturePipeOwner
from t02_capture_windows_host import CaptureSupervisorHost
from t02_capture_windows_pipe import WindowsCapturePipe
from t02_event_capture import CaptureStore
from t02_event_types import Hold


@dataclass(frozen=True, repr=False)
class PreparedTransfer:
    """Private bytes and borrowed child handles for a single native spawn."""

    descriptor: InheritedCapture
    pipes: CapturePipeHandles
    jobs: tuple[int, int]
    wire: bytes


def prepare_transfer(
    descriptor_clock: Callable[[], int],
    wall: Callable[[], int],
    packet: CapturePacket,
    store: CaptureStore,
    pipe_owner: CapturePipeOwner,
    job_owner: OwnedCaptureJobs,
    duplicate_for_child: Callable[[int], int],
    correlation: str,
    intake: int,
    cleanup: int,
) -> PreparedTransfer:
    """Pin both Job limits before the supervisor process can even be created."""
    if (not InheritedCapture(PeerBinding((1, 2, 3), correlation, intake, cleanup),
                             packet.approval.head, packet.approval.digest
                             ).verifies_packet_window(packet, descriptor_clock, wall)
        or store.status()[0] != "claimed"):
        raise Hold("capture transfer not admitted")
    try:
        job_owner.allocate(intake)
        pipes = pipe_owner.prepare(intake)
        descriptor = InheritedCapture(PeerBinding.from_owner(pipes, correlation, intake, cleanup),
                                      packet.approval.head, packet.approval.digest)
        jobs = job_owner.inherited(duplicate_for_child, intake)
        wire = make_handoff(descriptor, packet, store, jobs, descriptor_clock, wall)
    except (Hold, OSError, ValueError):
        try:
            pipe_owner.close()
        finally:
            job_owner.close()
        raise Hold("capture transfer preparation held") from None
    return PreparedTransfer(descriptor, pipes, jobs, wire)


def start_transferred_host(
    transfer: PreparedTransfer,
    host: CaptureSupervisorHost,
    pipe_owner: CapturePipeOwner,
    mono: Callable[[], int],
    job_owner: OwnedCaptureJobs,
) -> WindowsCapturePipe:
    """Start the fixed helper once, then deliver only its authenticated private packet."""
    deadline = transfer.descriptor.peer.intake_ms
    try:
        if mono() >= deadline or not host.start_transferred(transfer.descriptor, transfer.jobs):
            raise Hold("capture supervisor start unknown")
    finally:
        try:
            pipe_owner.release_supervisor_copies()
        finally:
            job_owner.release_child_copies()
    if mono() >= deadline:
        raise Hold("capture supervisor handoff expired")
    pipe = WindowsCapturePipe(*transfer.pipes.controller, mono)
    write_handoff(pipe, transfer.wire, deadline)
    return pipe
