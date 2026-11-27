"""Controller side of the fixed capture host protocol; no channel factory."""

from collections.abc import Callable
from typing import Protocol

from t02_capture_supervisor import Command, HostStatus
from t02_event_types import Hold


class CaptureHostChannel(Protocol):
    """A separately owned fixed host, never a general process interface."""

    def arm(self, intake_deadline: int, cleanup_deadline: int) -> HostStatus: ...
    def request(self, command: Command, deadline: int) -> HostStatus: ...
    def signal_stop(self) -> None: ...
    def stop_witness(self, deadline: int) -> HostStatus: ...


class CaptureHostedRoles:
    """Relate one controller attempt to its exact host-owned terminal status."""

    def __init__(
        self, channel: CaptureHostChannel, intake: int, cleanup: int, clock: Callable[[], int],
        wait_candidate: Callable[[int], None],
    ) -> None:
        self._channel = channel
        self._intake = intake
        self._cleanup = cleanup
        self._clock = clock
        self._wait_candidate = wait_candidate
        self._phase = "new"
        self._listener_attempted = False
        self._runtime_attempted = False
        self._stop_sent = False

    def arm(self, cleanup_deadline_ms: int) -> None:
        """Allow one host admission before either role."""
        if (self._phase != "new" or self._clock() >= self._intake
            or cleanup_deadline_ms != self._cleanup):
            raise Hold("capture host arm held")
        self._phase = "arm-attempted"
        reply = self._channel.arm(self._intake, self._cleanup)
        if reply != HostStatus("armed", False, False) or self._clock() >= self._intake:
            raise Hold("capture host readiness unknown")
        self._phase = reply.phase

    def start_listener(self, intake_deadline_ms: int) -> None:
        """Request only the fixed listener role once."""
        if self._phase != "armed" or intake_deadline_ms != self._intake or self._clock() >= self._intake:
            raise Hold("capture listener start held")
        self._listener_attempted = True
        self._phase = "listener-attempted"
        reply = self._channel.request(Command.LISTENER, self._intake)
        if reply != HostStatus("listener-started", True, False) or self._clock() >= self._intake:
            raise Hold("capture listener readiness unknown")
        self._phase = reply.phase

    def start_runtime(self, intake_deadline_ms: int) -> None:
        """Request only the fixed runtime role after the listener."""
        if (self._phase != "listener-started" or intake_deadline_ms != self._intake
            or self._clock() >= self._intake):
            raise Hold("capture runtime start held")
        self._runtime_attempted = True
        self._phase = "runtime-attempted"
        reply = self._channel.request(Command.RUNTIME, self._intake)
        if reply != HostStatus("runtime-started", True, True) or self._clock() >= self._intake:
            raise Hold("capture runtime readiness unknown")
        self._phase = reply.phase

    def wait_candidate(self, intake_deadline_ms: int) -> None:
        """Wait only while the original intake window is open."""
        if (self._phase != "runtime-started" or intake_deadline_ms != self._intake
            or self._clock() >= self._intake):
            raise Hold("capture intake held")
        self._wait_candidate(self._intake)

    def signal_all(self) -> None:
        """Signal once without replacing the armed host or waiting for a role."""
        if not self._stop_sent:
            self._stop_sent = True
            self._phase = "stopping"
            self._channel.signal_stop()

    def confirmed_stopped(self, cleanup_deadline_ms: int) -> bool:
        """An ambiguous or contradictory remote witness is not success."""
        if not self._stop_sent or cleanup_deadline_ms != self._cleanup or self._clock() >= self._cleanup:
            return False
        result = self._channel.stop_witness(self._cleanup)
        return (
            result == HostStatus("confirmed", self._listener_attempted, self._runtime_attempted)
            and self._clock() < self._cleanup
        )
