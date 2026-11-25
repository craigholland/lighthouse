"""Run-bound child capability ledger for the trusted-account Windows proof."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from t02_capture_bootstrap import InheritedCapture
from t02_event_types import Hold

Role = Literal["coordinator", "supervisor", "listener"]


@dataclass(frozen=True, repr=False)
class TrustedInheritedCapabilities:
    """Bind each passed capability to the trusted fixed launcher's exact role/run.

    This is not an OS security boundary against hostile code at the launcher
    principal. Keep production release unbound. The caller supplies checks of
    the already inherited OS objects, not open-by-ID or adoption functions.
    """

    role: Role
    descriptor: InheritedCapture
    jobs: tuple[int, ...]
    pipe_valid: Callable[[int], bool]
    stop_valid: Callable[[int], bool]
    job_valid: Callable[[int], bool]

    def __post_init__(self) -> None:
        handles = self.descriptor.peer.handles + self.jobs
        if (self.role not in ("coordinator", "supervisor", "listener")
            or len(self.descriptor.peer.handles) != 3 or len(self.jobs) != (2 if self.role == "supervisor" else 0)
            or any(type(h) is not int or h <= 0 for h in handles)
            or len(set(handles)) != len(handles)):
            raise Hold("capture trusted launch capabilities held")

    def matches(self, role: Role, descriptor: InheritedCapture) -> bool:
        return self.role == role and self.descriptor == descriptor

    def _pipe(self, role: Role, handle: int) -> bool:
        return self.role == role and handle in self.descriptor.peer.handles[:2] and self.pipe_valid(handle)

    def _stop(self, role: Role, handle: int) -> bool:
        return self.role == role and handle == self.descriptor.peer.handles[2] and self.stop_valid(handle)

    def owns_coordinator_pipe(self, handle: int) -> bool:
        return self._pipe("coordinator", handle)

    def owns_coordinator_stop(self, handle: int) -> bool:
        return self._stop("coordinator", handle)

    def owns_pipe(self, handle: int) -> bool:
        return self._pipe("supervisor", handle)

    def owns_stop(self, handle: int) -> bool:
        return self._stop("supervisor", handle)

    def owns_jobs(self, handles: tuple[int, int]) -> bool:
        return self.role == "supervisor" and handles == self.jobs and all(self.job_valid(h) for h in handles)

    def owns_listener_pipe(self, handle: int) -> bool:
        return self._pipe("listener", handle)

    def owns_listener_stop(self, handle: int) -> bool:
        return self._stop("listener", handle)
