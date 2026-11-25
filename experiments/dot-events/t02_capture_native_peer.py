"""Fixed native peer I/O for the dormant capture supervisor."""

import struct
from collections.abc import Callable

from t02_capture_peer import PeerBinding, run_peer
from t02_capture_supervisor import CaptureSupervisor, Command, HostStatus
from t02_capture_windows_pipe import WindowsCapturePipe
from t02_event_types import Hold

_HEADER = struct.Struct("<I")


class WindowsPeerEvents:
    """Read fixed bounded frames and monitor stop independent of pipe traffic."""

    def __init__(self, pipe: WindowsCapturePipe, clock: Callable[[], int]) -> None:
        self._pipe = pipe
        self._clock = clock

    def _exact(self, count: int, deadline_ms: int) -> bytes:
        result = bytearray()
        while len(result) < count and self._clock() < self._pipe.terminal_deadline(deadline_ms):
            result.extend(self._pipe.read(count - len(result), deadline_ms))
        if len(result) != count or self._clock() >= self._pipe.terminal_deadline(deadline_ms):
            raise Hold("capture peer frame deadline")
        return bytes(result)

    def receive(self, deadline_ms: int, max_bytes: int) -> bytes | None:
        header = self._exact(_HEADER.size, deadline_ms)
        count, = _HEADER.unpack(header)
        if not 0 < count <= max_bytes - _HEADER.size:
            raise Hold("capture peer frame size held")
        return header + self._exact(count, deadline_ms)

    def send(self, frame: bytes, deadline_ms: int) -> None:
        self._pipe.write(frame, deadline_ms)

    def stopped(self) -> bool:
        return self._pipe.stopped()


def run_native_peer(binding: PeerBinding, host: CaptureSupervisor, clock: Callable[[], int]) -> HostStatus:
    """Internal composition only; public and helper entry points remain held."""
    def events(handles: tuple[int, int, int]) -> WindowsPeerEvents:
        def stop() -> None:
            host.command(Command.STOP)

        return WindowsPeerEvents(WindowsCapturePipe(
            *handles, clock, supervisor=True, on_stop=stop, cleanup_deadline=binding.cleanup_ms,
        ), clock)

    return run_peer(binding, host, events, clock)
