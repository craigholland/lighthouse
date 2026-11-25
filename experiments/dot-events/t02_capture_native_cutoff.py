"""Owned Windows cutoff primitives for the fixed detached capture owner."""

from __future__ import annotations

import ctypes as c
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

from t02_capture_bootstrap import InheritedCapture
from t02_capture_owned_jobs import OwnedCaptureJobs
from t02_capture_windows_host import CaptureSupervisorHost
from t02_event_types import Hold
from t02_event_windows import _Accounting, _ExtendedLimits, _kernel


@dataclass(frozen=True)
class CutoffReceipt:
    """Emergency cleanup must not manufacture an exact role-root receipt."""

    supervisor_root_exited: bool
    supervisor_job_empty: bool
    role_jobs_empty: bool


class FixedWindowsCutoff:
    """Allocate and operate solely on Jobs this owner created itself."""

    def __init__(self, python: Path, clock: Callable[[], int]) -> None:
        self._clock = clock
        self._native = _kernel()
        self.host = CaptureSupervisorHost(python, clock)
        self.roles = OwnedCaptureJobs(clock)
        self._supervisor: int | None = None
        self._root: int | None = None
        self._lock = Lock()
        self._intake = 0
        self._cleanup = 0
        self._started = False
        self._signal_taken = False

    def allocate_supervisor(self, intake: int, cleanup: int) -> None:
        """Pin the supervisor Job before a potentially blocked spawn is admitted."""
        with self._lock:
            if self._supervisor is not None or not self._clock() < intake < cleanup or self._signal_taken:
                raise Hold("capture independent owner held")
            job = self._native.CreateJobObjectW(None, None)
            limits = _ExtendedLimits()
            limits.basic.flags = 0x2000
            if not job:
                raise Hold("capture supervisor Job unavailable")
            if not self._native.SetInformationJobObject(job, 9, c.byref(limits), c.sizeof(limits)):
                self._native.CloseHandle(job)
                raise Hold("capture supervisor Job containment unavailable")
            self._supervisor = job
            self._intake, self._cleanup = intake, cleanup

    def start_fixed(
        self, descriptor: InheritedCapture, jobs: tuple[int, int],
        duplicate_noninheritable: Callable[[int], int],
    ) -> bool:
        """The spawn lane may block. The main detached deadline lane owns originals."""
        with self._lock:
            if (self._started or self._signal_taken or self._supervisor is None
                or descriptor.peer.intake_ms != self._intake or descriptor.peer.cleanup_ms != self._cleanup
                or self._clock() >= self._intake or not self.roles.confirm_child_copies(jobs)):
                raise Hold("capture fixed supervisor start held")
            self._started = True
            supervisor = self._supervisor
        launch_copy = duplicate_noninheritable(supervisor)
        if launch_copy <= 0 or launch_copy == supervisor or launch_copy in jobs:
            raise Hold("capture supervisor Job copy unknown")
        if self._clock() >= self._intake:
            self._native.CloseHandle(launch_copy)
            raise Hold("capture supervisor Job copy late")

        def before_resume(job: int, root: int) -> None:
            with self._lock:
                if job != launch_copy or self._signal_taken or self._root is not None or self._clock() >= self._intake:
                    raise Hold("capture supervisor root handoff held")
            witness = duplicate_noninheritable(root)
            if witness <= 0 or witness == root or witness == job or witness in jobs:
                raise Hold("capture supervisor root witness unknown")
            with self._lock:
                if self._signal_taken or self._clock() >= self._intake:
                    self._native.CloseHandle(witness)
                    raise Hold("capture supervisor root handoff held")
                self._root = witness

        return self.host.start_owned_transfer(descriptor, jobs, launch_copy, before_resume)

    def stop_due(self) -> CutoffReceipt:
        """Terminate both exact role Jobs and supervisor without waiting on spawn."""
        with self._lock:
            if self._supervisor is None or self._signal_taken or self._clock() < self._intake:
                raise Hold("capture cutoff not due")
            self._signal_taken = True
            job, root = self._supervisor, self._root
        signal_host = bool(self._native.TerminateJobObject(job, 1))
        try:
            self.roles.signal_both()
        except (Hold, OSError):
            return CutoffReceipt(False, False, False)
        remaining = self._cleanup - self._clock()
        exited = bool(root and remaining > 0 and self._native.WaitForSingleObject(root, remaining) == 0)
        account = _Accounting()
        host_empty = bool(signal_host and self._clock() < self._cleanup and self._native.QueryInformationJobObject(
            job, 1, c.byref(account), c.sizeof(account), None,
        ) and account.active == 0)
        return CutoffReceipt(exited and self._clock() < self._cleanup, host_empty, self.roles.empty(self._cleanup))

    def close(self) -> None:
        """Relinquish only owned originals; close is never a shutdown receipt."""
        with self._lock:
            job, root = self._supervisor, self._root
            self._supervisor = self._root = None
        try:
            for handle in (job, root):
                if handle:
                    self._native.CloseHandle(handle)
        finally:
            self.roles.close()
