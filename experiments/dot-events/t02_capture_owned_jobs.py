"""The detached owner arms both exact capture Jobs before role creation."""

from __future__ import annotations

import ctypes as c
from collections.abc import Callable

from t02_event_types import Hold
from t02_event_windows import _Accounting, _ExtendedLimits, _kernel


class OwnedCaptureJobs:
    """Own the listener and runtime Jobs, never a caller-specified process."""

    def __init__(self, clock: Callable[[], int]) -> None:
        self._clock = clock
        self._native = _kernel()
        self._handles: tuple[int, int] | None = None
        self._attempted = False
        self._delegated = False
        self._signaled = False
        self._child_copies: tuple[int, int] | None = None

    def allocate(self, deadline: int) -> tuple[int, int]:
        """Create exactly two initially empty no-breakaway Jobs before handoff."""
        if self._attempted or self._clock() >= deadline:
            raise Hold("capture role Job allocation held")
        self._attempted = True
        jobs: list[int] = []
        try:
            for _ in range(2):
                if self._clock() >= deadline:
                    raise Hold("capture role Job allocation expired")
                handle = self._native.CreateJobObjectW(None, None)
                if not handle or handle in jobs:
                    raise Hold("capture role Job allocation unknown")
                jobs.append(handle)
                limits = _ExtendedLimits()
                limits.basic.flags = 0x2000
                if not self._native.SetInformationJobObject(handle, 9, c.byref(limits), c.sizeof(limits)):
                    raise Hold("capture role Job containment unavailable")
            if self._clock() >= deadline:
                raise Hold("capture role Job allocation expired")
            self._handles = (jobs[0], jobs[1])
            return self._handles
        except (Hold, OSError):
            for job in jobs:
                self._native.CloseHandle(job)
            raise Hold("capture role Jobs held") from None

    def inherited(self, duplicate_exact: Callable[[int], int], deadline: int) -> tuple[int, int]:
        """Borrow only child-specific safe duplicates; originals stay in this owner."""
        if self._handles is None or self._delegated or self._signaled or self._clock() >= deadline:
            raise Hold("capture role Jobs not available")
        self._delegated = True
        child: list[int] = []
        try:
            for handle in self._handles:
                if self._clock() >= deadline:
                    raise Hold("capture Job handoff expired")
                value = duplicate_exact(handle)
                if value <= 0 or value in child or value in self._handles:
                    raise Hold("capture Job handoff unknown")
                child.append(value)
            if self._clock() >= deadline:
                raise Hold("capture Job handoff expired")
            self._child_copies = (child[0], child[1])
            return self._child_copies
        except (Hold, OSError):
            for value in child:
                self._native.CloseHandle(value)
            raise Hold("capture Job handoff held") from None

    def confirm_child_copies(self, jobs: tuple[int, int]) -> bool:
        return not self._signaled and self._child_copies == jobs

    def signal_both(self) -> None:
        """Terminate both owned Jobs before waiting even if one signal fails."""
        if self._handles is None or self._signaled:
            raise Hold("capture role Job stop unavailable")
        self._signaled = True
        sent = True
        for handle in self._handles:
            try:
                sent = bool(self._native.TerminateJobObject(handle, 1)) and sent
            except OSError:
                sent = False
        if not sent:
            raise Hold("capture role Job stop unknown")

    def empty(self, deadline: int) -> bool:
        """Empty accounting is required but cannot replace exact root receipts."""
        if self._handles is None or not self._signaled or self._clock() >= deadline:
            return False
        observed: list[bool] = []
        for handle in self._handles:
            data = _Accounting()
            observed.append(bool(
                self._native.QueryInformationJobObject(handle, 1, c.byref(data), c.sizeof(data), None)
            ) and data.active == 0)
        return all(observed) and self._clock() < deadline

    def release_child_copies(self) -> None:
        """Close the parent's inheritable duplicate copies after one spawn attempt."""
        copies, self._child_copies = self._child_copies, None
        if copies is not None:
            for handle in copies:
                self._native.CloseHandle(handle)

    def close(self) -> None:
        self.release_child_copies()
        handles, self._handles = self._handles, None
        if handles is not None:
            for handle in handles:
                self._native.CloseHandle(handle)
