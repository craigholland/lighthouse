"""Dormant containment for the fixed capture watchdog host."""

from collections.abc import Callable
from pathlib import Path

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
