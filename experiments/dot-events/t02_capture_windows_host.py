"""Dormant containment for the fixed capture watchdog host."""

from collections.abc import Callable
from pathlib import Path

from t02_capture_bootstrap import InheritedCapture
from t02_capture_trusted import bound_child_environment
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


    def start_transferred(self, descriptor: InheritedCapture, jobs: tuple[int, int]) -> bool:
        """Inherit only the three private endpoints and exact two preowned Jobs."""
        inherited = (*descriptor.peer.handles, *jobs)
        if len(inherited) != 5 or min(inherited) <= 0 or len(set(inherited)) != 5:
            raise Hold("capture supervisor handle allowlist held")
        return self._start_owned(
            self._python, ["-I", str(_HOST)], bound_child_environment("supervisor", descriptor, jobs), descriptor.peer.intake_ms,
            bind_at_creation=True, inherited=inherited,
        )

    def start_owned_transfer(
        self, descriptor: InheritedCapture, jobs: tuple[int, int], supervisor_job: int,
        before_resume: Callable[[int, int], None],
    ) -> bool:
        # The detached owner passes only a duplicate of its own supervisor Job.
        inherited = (*descriptor.peer.handles, *jobs)
        if (len(inherited) != 5 or min(inherited) <= 0 or len(set(inherited)) != 5
            or supervisor_job <= 0 or supervisor_job in inherited):
            raise Hold("capture owned supervisor allowlist held")
        return self._start_owned(
            self._python, ["-I", str(_HOST)], bound_child_environment("supervisor", descriptor, jobs), descriptor.peer.intake_ms,
            bind_at_creation=True, inherited=inherited, preowned_job=supervisor_job,
            before_resume=before_resume,
        )


class CaptureListenerHost(_OwnedWindowsJob):
    """Own a distinct fixed listener helper before either role runs."""

    def __init__(self, trusted_python: Path, clock: Callable[[], int]) -> None:
        if not trusted_python.is_absolute() or trusted_python.name.casefold() != "python.exe":
            raise Hold("capture listener interpreter not bound")
        super().__init__(clock)
        self._python = trusted_python

    def start_bound(self, descriptor: InheritedCapture, deadline_ms: int, *, preowned_job: int | None = None) -> bool:
        if deadline_ms != descriptor.peer.intake_ms:
            raise Hold("capture listener startup bound differs")
        script = Path(__file__).with_name("t02_capture_listener.py")
        return self._start_owned(
            self._python, ["-I", str(script)], bound_child_environment("listener", descriptor), deadline_ms,
            bind_at_creation=True, inherited=descriptor.peer.handles, preowned_job=preowned_job,
        )
