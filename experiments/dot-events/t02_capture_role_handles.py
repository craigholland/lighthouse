"""Exact listener/runtime witness ownership inside the separate capture host."""

from __future__ import annotations

import ctypes as c
from collections.abc import Callable
from ctypes import wintypes as w

from t02_event_types import Hold
from t02_event_windows import _Accounting, _kernel, _OwnedWindowsJob


class CaptureRoleWitness:
    """Receive Job/root handles from one locally owned role, never a caller PID."""

    def __init__(self, role: _OwnedWindowsJob, clock: Callable[[], int]) -> None:
        self._kernel = _kernel()
        self._clock = clock
        self._job, self._root = role._handoff_exact_handles()
        self._stopped = False
        self._confirmed: bool | None = None

    def signal(self) -> None:
        """Signal this exact role tree once without waiting."""
        if self._stopped:
            return
        self._stopped = True
        if not self._kernel.TerminateJobObject(self._job, 1):
            raise Hold("capture role termination signal unknown")

    def confirm_exact_stop(self, deadline_ms: int) -> bool:
        """Check exact root exit plus empty Job before relinquishing the witness."""
        if not self._stopped or self._confirmed is not None:
            return self._confirmed is True
        k = self._kernel
        remaining = deadline_ms - self._clock()
        observed = _Accounting()
        root_exited = remaining > 0 and k.WaitForSingleObject(self._root, remaining) == 0
        job_empty = root_exited and bool(
            k.QueryInformationJobObject(self._job, 1, c.byref(observed), c.sizeof(observed), None)
        ) and observed.active == 0
        self._confirmed = bool(job_empty and self._clock() < deadline_ms)
        return self._confirmed

    def close(self) -> None:
        """Relinquish exact handles once; closing is not a cessation observation."""
        job, root = self._job, self._root
        self._job = self._root = 0
        if job:
            self._kernel.CloseHandle(w.HANDLE(job))
        if root:
            self._kernel.CloseHandle(w.HANDLE(root))
