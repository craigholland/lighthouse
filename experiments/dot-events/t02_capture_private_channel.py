"""Bounded capture-controller wire tied to an inherited private pipe capability."""

from __future__ import annotations

import struct
from collections.abc import Callable
from typing import Protocol

from t02_capture_supervisor import CaptureSupervisor, Command, HostStatus
from t02_event_types import Hold, decode, encode

_MAX_FRAME = 1024
_HEADER = struct.Struct("<I")
_PHASES = {"armed", "listener-started", "runtime-started", "confirmed", "cleanup-unknown"}


class OwnedPipe(Protocol):
    """The adapter owns exact private handles and bounds each I/O to the deadline."""

    def write(self, data: bytes, deadline_ms: int) -> None: ...
    def read(self, count: int, deadline_ms: int) -> bytes: ...
    def signal_stop(self) -> None: ...


class CapturePrivateChannel:
    """Ordered, one-request framing with no commands, URLs or paths from callers."""

    def __init__(self, pipe: OwnedPipe, correlation: str, clock: Callable[[], int]) -> None:
        if len(correlation) != 64 or any(c not in "0123456789abcdef" for c in correlation):
            raise Hold("capture channel correlation unavailable")
        self._pipe = pipe
        self._correlation = correlation
        self._clock = clock
        self._sequence = 0
        self._held = False
        self._stopped = False

    def _read_exact(self, count: int, deadline: int) -> bytes:
        chunks: list[bytes] = []
        while count > 0 and self._clock() < deadline:
            data = self._pipe.read(count, deadline)
            if not data or len(data) > count:
                raise Hold("capture channel short read")
            chunks.append(data)
            count -= len(data)
        if count or self._clock() >= deadline:
            raise Hold("capture channel deadline")
        return b"".join(chunks)

    def _exchange(self, action: str, deadline: int, **extra: int) -> HostStatus:
        if self._held or self._clock() >= deadline:
            raise Hold("capture channel held")
        self._sequence += 1
        seq = self._sequence
        request = encode({"action": action, "seq": seq, "correlation": self._correlation} | extra)
        try:
            self._pipe.write(_HEADER.pack(len(request)) + request, deadline)
            size, = _HEADER.unpack(self._read_exact(_HEADER.size, deadline))
            if not 0 < size <= _MAX_FRAME:
                raise Hold("capture channel invalid frame length")
            response = decode(self._read_exact(size, deadline), _MAX_FRAME)
            phase = response.get("phase")
            listener, runtime = response.get("listener_attempted"), response.get("runtime_attempted")
            if (response.keys() != {"seq", "correlation", "phase", "listener_attempted", "runtime_attempted"}
                or type(response["seq"]) is not int or response["seq"] != seq
                or response["correlation"] != self._correlation or not isinstance(phase, str) or phase not in _PHASES
                or type(listener) is not bool or type(runtime) is not bool or (runtime and not listener)
                or self._clock() >= deadline):
                raise Hold("capture channel invalid receipt")
            return HostStatus(phase, listener, runtime)
        except (Hold, OSError):
            self._held = True
            raise Hold("capture channel result unknown") from None

    def arm(self, intake_deadline: int, cleanup_deadline: int) -> HostStatus:
        if self._sequence or self._stopped or not self._clock() < intake_deadline < cleanup_deadline:
            raise Hold("capture channel arm held")
        return self._exchange("arm", intake_deadline, intake=intake_deadline, cleanup=cleanup_deadline)

    def request(self, command: Command, deadline: int) -> HostStatus:
        if self._stopped or command not in (Command.LISTENER, Command.RUNTIME):
            raise Hold("capture channel command held")
        return self._exchange(command.value, deadline)

    def signal_stop(self) -> None:
        # Separate native event: never queues behind an ambiguous or stalled pipe.
        if not self._stopped:
            self._stopped = True
            self._pipe.signal_stop()

    def stop_witness(self, deadline: int) -> HostStatus:
        if not self._stopped:
            raise Hold("capture channel stop was not signaled")
        return self._exchange("status", deadline)


class CaptureHostFrames:
    """Host-side ordered capability protocol, bound to one admitted operation."""

    def __init__(
        self, host: CaptureSupervisor, correlation: str, intake: int, cleanup: int,
        clock: Callable[[], int],
    ) -> None:
        if (len(correlation) != 64 or any(c not in "0123456789abcdef" for c in correlation)
            or not clock() < intake < cleanup):
            raise Hold("invalid capture host binding")
        self._host = host
        self._correlation = correlation
        self._intake, self._cleanup = intake, cleanup
        self._clock = clock
        self._seq = 0
        self._held = False

    def stop_event(self) -> HostStatus:
        """Handle independent stop even when the pipe is held."""
        return self._host.command(Command.STOP)

    def on_frame(self, frame: bytes) -> bytes:
        """Accept one fixed message; malformed input cannot reach a role."""
        if self._held:
            raise Hold("capture host channel held")
        try:
            if not _HEADER.size < len(frame) <= _HEADER.size + _MAX_FRAME:
                raise Hold("capture host frame held")
            size, = _HEADER.unpack(frame[:_HEADER.size])
            data = frame[_HEADER.size:]
            if size != len(data):
                raise Hold("capture host frame size held")
            request = decode(data, _MAX_FRAME)
            action, seq = request.get("action"), request.get("seq")
            if (not isinstance(action, str) or type(seq) is not int or seq != self._seq + 1
                or request.get("correlation") != self._correlation):
                raise Hold("capture host binding held")
            keys = {"action", "seq", "correlation"}
            deadline = self._cleanup if action == "status" else self._intake
            if self._clock() >= deadline:
                raise Hold("capture host message expired")
            if action == "arm" and self._seq == 0:
                if (request.keys() != keys | {"intake", "cleanup"} or request["intake"] != self._intake
                    or request["cleanup"] != self._cleanup):
                    raise Hold("capture host deadlines differ")
                status = self._host.tick()
            elif self._seq >= 1 and request.keys() == keys and action in {"listener", "runtime", "status"}:
                status = self._host.tick() if action == "status" else self._host.command(Command(action))
            else:
                raise Hold("capture host action held")
            if self._clock() >= deadline:
                raise Hold("capture host response expired")
            self._seq = seq
            result = encode({"seq": seq, "correlation": self._correlation, "phase": status.phase,
                             "listener_attempted": status.listener_attempted,
                             "runtime_attempted": status.runtime_attempted})
            return _HEADER.pack(len(result)) + result
        except (Hold, OSError):
            self._held = True
            raise Hold("capture host protocol held") from None
