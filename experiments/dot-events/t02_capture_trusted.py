"""Run-bound child capability ledger for the trusted-account Windows proof."""

from __future__ import annotations

import ctypes as c
import os
from collections.abc import Callable
from ctypes import wintypes as w
from dataclasses import dataclass
from typing import Literal

from t02_capture_bootstrap import ENVIRONMENT_KEY, InheritedCapture
from t02_event_types import Hold, decode, encode
from t02_event_windows import _Accounting, _kernel

Role = Literal["coordinator", "supervisor", "listener"]
ObjectChecks = tuple[Callable[[int], bool], Callable[[int], bool], Callable[[int], bool]]
CHILD_LEDGER = "LIGHTHOUSE_T02_OWNED_CHILD"


def bound_child_environment(
    role: Role, descriptor: InheritedCapture, jobs: tuple[int, ...] = (),
) -> dict[str, str]:
    TrustedInheritedCapabilities(role, descriptor, jobs, lambda _: True, lambda _: True, lambda _: True)
    raw = descriptor.to_environment()
    return raw | {CHILD_LEDGER: encode({"role": role, "descriptor": raw[ENVIRONMENT_KEY], "jobs": jobs}).decode("ascii")}



@dataclass(frozen=True, repr=False)
class TrustedInheritedCapabilities:
    """Bind each passed capability to the trusted fixed launcher's exact role/run.

    This is not an OS security boundary against hostile code at the launcher
    principal. Only fixed launchers supply this environment. Checks apply to
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


class _UnicodeString(c.Structure):
    _fields_ = [("length", w.USHORT), ("maximum", w.USHORT), ("buffer", c.c_void_p)]


def handle_checks() -> ObjectChecks:
    k = _kernel()
    filetype = k.GetFileType
    filetype.restype, filetype.argtypes = w.DWORD, (w.HANDLE,)
    query = c.WinDLL("ntdll").NtQueryObject
    query.restype, query.argtypes = w.LONG, (w.HANDLE, w.ULONG, c.c_void_p, w.ULONG, c.c_void_p)

    def is_event(handle: int) -> bool:
        data = c.create_string_buffer(1024)
        if query(handle, 2, c.byref(data), c.sizeof(data), None) != 0:
            return False
        info = _UnicodeString.from_buffer(data)
        first = c.addressof(data)
        pointer = info.buffer
        return bool(
            info.length == 10 and 10 <= info.maximum <= c.sizeof(data)
            and pointer is not None and first <= pointer <= first + c.sizeof(data) - info.maximum
            and c.wstring_at(pointer, 5) == "Event"
        )

    def is_job(handle: int) -> bool:
        data = _Accounting()
        return bool(k.QueryInformationJobObject(handle, 1, c.byref(data), c.sizeof(data), None))

    return lambda handle: filetype(handle) == 3, is_event, is_job


def read_child_binding(role: Role, clock: Callable[[], int], *, checks: Callable[[], ObjectChecks] = handle_checks) -> tuple[TrustedInheritedCapabilities, str]:
    data: object = decode(os.environ.get(CHILD_LEDGER, "").encode("ascii"), 1024)
    if (not isinstance(data, dict) or set(data) != {"role", "descriptor", "jobs"}
        or data.get("role") != role or not isinstance(data["descriptor"], str)
        or not isinstance(data["jobs"], list) or any(type(item) is not int for item in data["jobs"])):
        raise Hold("capture capability ledger held")
    pipe, stop, job = checks()
    expected = InheritedCapture.accept(data["descriptor"], clock, pipe, stop)
    ledger = TrustedInheritedCapabilities(role, expected, tuple(data["jobs"]), pipe, stop, job)
    raw = os.environ.get(ENVIRONMENT_KEY, "")
    owns_pipe, owns_stop = {
        "coordinator": (ledger.owns_coordinator_pipe, ledger.owns_coordinator_stop),
        "supervisor": (ledger.owns_pipe, ledger.owns_stop),
        "listener": (ledger.owns_listener_pipe, ledger.owns_listener_stop),
    }[role]
    observed = InheritedCapture.accept(raw, clock, owns_pipe, owns_stop)
    if not ledger.matches(role, observed):
        raise Hold("capture inherited capabilities do not match launch")
    return ledger, raw
