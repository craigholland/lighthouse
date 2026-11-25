"""Inert watchdog policy tests; no process, socket, or real wait."""

from collections.abc import Callable
from dataclasses import dataclass

from t02_capture_watchdog import CaptureWatchdog
from t02_event_types import Hold


@dataclass
class Clock:
    now: int = 0

    def read(self) -> int:
        return self.now


@dataclass
class Role:
    name: str
    trace: list[str]
    stop: Callable[[], bool]
    signal_failure: bool = False

    def signal(self) -> None:
        self.trace.append("signal-" + self.name)
        if self.signal_failure:
            raise Hold("synthetic signal failure")

    def confirm_exact_stop(self, deadline_ms: int) -> bool:
        assert deadline_ms == 30
        self.trace.append("confirm-" + self.name)
        return self.stop()


def test_independent_observer_signals_both_at_original_cutoff() -> None:
    clock = Clock()
    trace: list[str] = []
    listener = Role("listener", trace, lambda: True)
    runtime = Role("runtime", trace, lambda: True)
    watchdog = CaptureWatchdog(clock.read, listener, runtime, 20, 30)
    clock.now = 19
    assert watchdog.observe() == "armed" and not trace
    clock.now = 20
    assert watchdog.observe() == "confirmed"
    assert trace == ["signal-listener", "signal-runtime", "confirm-listener", "confirm-runtime"]
    assert watchdog.observe(stop_requested=True) == "confirmed"
    assert len(trace) == 4


def test_failed_or_late_cleanup_never_upgrades_or_rearms() -> None:
    clock = Clock()
    trace: list[str] = []

    def late() -> bool:
        clock.now = 30
        return True

    listener = Role("listener", trace, late, signal_failure=True)
    runtime = Role("runtime", trace, lambda: True)
    watchdog = CaptureWatchdog(clock.read, listener, runtime, 20, 30)
    assert watchdog.observe(stop_requested=True) == "cleanup-unknown"
    assert trace == ["signal-listener", "signal-runtime", "confirm-listener"]
    clock.now = 10
    assert watchdog.observe() == "cleanup-unknown"
    assert len(trace) == 3
