"""Guarded fixed supervisor bootstrap over already inherited capabilities."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from t02_capture_pipe_owner import CapturePipeHandles
from t02_capture_private_channel import CaptureHostFrames
from t02_capture_supervisor import CaptureSupervisor, HostStatus
from t02_event_types import Hold

_MAX_FRAME = 1028


class PeerEvents(Protocol):
    """An independent owner observes stop rather than depending on a command."""

    def receive(self, deadline_ms: int, max_bytes: int) -> bytes | None: ...
    def send(self, frame: bytes, deadline_ms: int) -> None: ...
    def stopped(self) -> bool: ...


@dataclass(frozen=True, repr=False)
class PeerBinding:
    """Exact capabilities and original monotonic deadlines of one admitted run."""

    handles: tuple[int, int, int]
    correlation: str
    intake_ms: int
    cleanup_ms: int

    @classmethod
    def from_owner(
        cls, handles: CapturePipeHandles, correlation: str, intake_ms: int, cleanup_ms: int,
    ) -> PeerBinding:
        """Bind only the supervisor side of provisioned private handles."""
        if (len(set((*handles.controller, *handles.supervisor))) != 6
            or min(*handles.controller, *handles.supervisor) <= 0):
            raise Hold("invalid capture peer capabilities")
        return cls(handles.supervisor, correlation, intake_ms, cleanup_ms)


def run_peer(
    binding: PeerBinding,
    host: CaptureSupervisor,
    event_factory: Callable[[tuple[int, int, int]], PeerEvents],
    clock: Callable[[], int],
) -> HostStatus:
    """Glue the exact handle capability to a fixed two-role host, with no launch path."""
    if (len(set(binding.handles)) != 3 or min(binding.handles) <= 0
        or not clock() < binding.intake_ms < binding.cleanup_ms):
        raise Hold("capture peer unavailable")
    frames = CaptureHostFrames(host, binding.correlation, binding.intake_ms, binding.cleanup_ms, clock)
    events = event_factory(binding.handles)
    # One arm, at most two starts, and one terminal status request. There is
    # no retry or unbounded receive loop even if the peer is silent.
    try:
        for turn in range(4):
            if events.stopped():
                frames.stop_event()
            deadline = binding.cleanup_ms if turn == 3 or host.status().phase in {"confirmed", "cleanup-unknown"} else binding.intake_ms
            if clock() >= deadline:
                break
            frame = events.receive(deadline, _MAX_FRAME)
            if events.stopped():
                frames.stop_event()
                deadline = binding.cleanup_ms
            if frame is None or clock() >= deadline:
                break
            response = frames.on_frame(frame)
            if clock() >= deadline:
                break
            events.send(response, deadline)
            if host.status().phase in {"confirmed", "cleanup-unknown"}:
                break
    except (Hold, OSError, KeyboardInterrupt):
        pass
    return frames.stop_event()
