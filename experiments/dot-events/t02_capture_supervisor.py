"""Fixed supervisor state machine; no direct operational handoff."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Protocol


class Command(Enum):
    LISTENER = "listener"
    RUNTIME = "runtime"
    STOP = "stop"


class HostedRole(Protocol):
    """Fixed role endpoint with an already owned exact stop receipt."""

    def request_start(self, deadline: int) -> bool: ...
    def signal(self) -> None: ...
    def confirm_exact_stop(self, deadline_ms: int) -> bool: ...


class TerminalOwner(Protocol):
    """Sole owner of capture sealing and terminal disposition."""

    def seal(self) -> bool: ...
    def finish(self, confirmed: bool) -> bool: ...


@dataclass(frozen=True)
class HostStatus:
    """Only fixed dispositions; no paths, credentials, or process IDs."""

    phase: str
    listener_attempted: bool
    runtime_attempted: bool


class CaptureSupervisor:
    """Own the two roles; the supervisor's clock can stop them without a caller."""

    def __init__(
        self, clock: Callable[[], int], intake_deadline: int, cleanup_deadline: int,
        listener: HostedRole, runtime: HostedRole,
        terminal: TerminalOwner | None = None,
    ) -> None:
        # Keep direct script import inert even under isolated Python.
        from t02_capture_watchdog import CaptureWatchdog
        from t02_event_types import Hold
        if not clock() < intake_deadline < cleanup_deadline:
            raise Hold("capture supervisor expired")
        self._clock = clock
        self._intake = intake_deadline
        self._listener = listener
        self._runtime = runtime
        self._terminal = terminal
        self._cleanup = cleanup_deadline
        self._finalized = False
        self._watchdog = CaptureWatchdog(
            clock, listener, runtime, intake_deadline, cleanup_deadline,
            terminal.seal if terminal is not None else lambda: True,
        )
        self._phase = "armed"
        self._listener_attempted = False
        self._runtime_attempted = False

    def tick(self) -> HostStatus:
        """The independent host must call this even without a controller message."""
        outcome = self._watchdog.observe()
        if outcome != "armed":
            self._finish(outcome)
        return self.status()

    def status(self) -> HostStatus:
        """Take a local fixed status snapshot; not a remote handle attestation."""
        return HostStatus(self._phase, self._listener_attempted, self._runtime_attempted)

    def command(self, command: Command) -> HostStatus:
        """Accept fixed in-order single attempts and never rearm."""
        from t02_event_types import Hold
        self.tick()
        if self._phase in {"confirmed", "cleanup-unknown"}:
            return self.status()
        if command is Command.STOP:
            return self._stop()
        try:
            if command is Command.LISTENER and self._phase == "armed":
                self._listener_attempted = True
                if self._listener.request_start(self._intake) and self._clock() < self._intake:
                    self._phase = "listener-started"
                    return self.status()
            if command is Command.RUNTIME and self._phase == "listener-started":
                self._runtime_attempted = True
                if self._runtime.request_start(self._intake) and self._clock() < self._intake:
                    self._phase = "runtime-started"
                    return self.status()
        except (Hold, OSError):
            pass
        return self._stop()

    def _stop(self) -> HostStatus:
        self._finish(self._watchdog.observe(stop_requested=True))
        return self.status()


    def _finish(self, outcome: str) -> None:
        from t02_event_types import Hold
        if self._finalized:
            return
        self._finalized = True
        self._phase = outcome
        if self._terminal is not None:
            try:
                accepted = self._terminal.finish(outcome == "confirmed" and self._clock() < self._cleanup)
                if not accepted or self._clock() >= self._cleanup:
                    self._phase = "cleanup-unknown"
            except (Hold, OSError):
                self._phase = "cleanup-unknown"


def main() -> int:
    """Refuse direct invocation without an admitted private control channel."""
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
