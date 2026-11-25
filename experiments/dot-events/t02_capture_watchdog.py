"""Fixed capture watchdog policy for an independently hosted owner.

This policy does not launch the hosting process. Running it on the control
thread would not establish independent ownership.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from t02_event_types import Hold


class OwnedCessation(Protocol):
    """One already-owned role; signal must not wait for role completion."""

    def signal(self) -> None: ...
    def confirm_exact_stop(self, deadline_ms: int) -> bool: ...


class CaptureWatchdog:
    """One absolute deadline and two fixed witnesses; no rearm."""

    def __init__(
        self,
        clock: Callable[[], int],
        listener: OwnedCessation,
        runtime: OwnedCessation,
        signal_cutoff_ms: int,
        cleanup_cutoff_ms: int,
        seal_intake: Callable[[], bool] = lambda: True,
    ) -> None:
        if not clock() < signal_cutoff_ms < cleanup_cutoff_ms:
            raise Hold("capture watchdog bound unavailable")
        self._clock = clock
        self._roles = (listener, runtime)
        self._signal_cutoff = signal_cutoff_ms
        self._cleanup_cutoff = cleanup_cutoff_ms
        self._seal_intake = seal_intake
        self._sealed = False
        self._outcome = "armed"

    def observe(self, *, stop_requested: bool = False) -> str:
        """An independent host polls this policy even if the controller stalls."""
        if self._sealed or (not stop_requested and self._clock() < self._signal_cutoff):
            return self._outcome

        self._sealed = True
        self._outcome = "cleanup-unknown"
        signaled = True
        for role in self._roles:
            try:
                role.signal()
            except (Hold, OSError):
                signaled = False

        try:
            confirmed = self._seal_intake()
        except (Hold, OSError):
            confirmed = False
        for role in self._roles:
            if self._clock() >= self._cleanup_cutoff:
                confirmed = False
                break
            try:
                observed = role.confirm_exact_stop(self._cleanup_cutoff)
                confirmed = observed and confirmed
            except (Hold, OSError):
                confirmed = False

        if signaled and confirmed and self._clock() < self._cleanup_cutoff:
            self._outcome = "confirmed"
        return self._outcome
