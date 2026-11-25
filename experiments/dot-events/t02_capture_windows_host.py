"""Dormant containment for the fixed capture watchdog host."""

from collections.abc import Callable
from pathlib import Path

from t02_capture_bootstrap import InheritedCapture
from t02_event_types import Hold
from t02_event_windows import _OwnedWindowsJob

_HOST = Path(__file__).with_name("t02_capture_supervisor.py")


class CaptureSupervisorHost(_OwnedWindowsJob):
    """Own the fixed helper's entire Job independently of its inner controller."""

    def __init__(self, trusted_python: Path, clock: Callable[[], int]) -> None:
        if not trusted_python.is_absolute() or trusted_python.name.casefold() != "python.exe":
            raise Hold("capture supervisor interpreter not bound")
        super().__init__(clock)
        self._python = trusted_python

    def start(self, deadline_ms: int, *, private_handles: tuple[int, ...] = ()) -> bool:
        """Start only the fixed helper, suspended and atomically job-bound."""
        return self._start_owned(
            self._python, ["-I", str(_HOST)], {}, deadline_ms, bind_at_creation=True, inherited=private_handles,
        )

    def start_bound(self, descriptor: InheritedCapture, deadline_ms: int) -> bool:
        """Pass this exact descriptor and only its three inherited handles."""
        if deadline_ms != descriptor.peer.intake_ms:
            raise Hold("capture supervisor startup bound differs")
        return self._start_owned(
            self._python, ["-I", str(_HOST)], descriptor.to_environment(), deadline_ms,
            bind_at_creation=True, inherited=descriptor.peer.handles,
        )


class CaptureListenerHost(_OwnedWindowsJob):
    """Own a distinct fixed listener helper before either role runs."""

    def __init__(self, trusted_python: Path, clock: Callable[[], int]) -> None:
        if not trusted_python.is_absolute() or trusted_python.name.casefold() != "python.exe":
            raise Hold("capture listener interpreter not bound")
        super().__init__(clock)
        self._python = trusted_python

    def start_bound(self, descriptor: InheritedCapture, deadline_ms: int) -> bool:
        if deadline_ms != descriptor.peer.intake_ms:
            raise Hold("capture listener startup bound differs")
        script = Path(__file__).with_name("t02_capture_listener.py")
        return self._start_owned(
            self._python, ["-I", str(script)], descriptor.to_environment(), deadline_ms,
            bind_at_creation=True, inherited=descriptor.peer.handles,
        )
