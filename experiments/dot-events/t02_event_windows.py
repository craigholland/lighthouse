"""Dormant job-owned launcher for the single pinned T02 vendor runtime.

The CLI does not instantiate this module or turn off the outer activation hold.
"""

import ctypes as c
import hashlib
import os
import re
import subprocess
import time
from collections.abc import Callable
from ctypes import wintypes as w
from pathlib import Path

from t02_event_gate import Packet
from t02_event_https import remaining
from t02_event_types import Hold

_DWORD = w.DWORD
_HANDLE = w.HANDLE
_POINTER = c.c_void_p
_QWORD = c.c_ulonglong


class _Startup(c.Structure):
    _fields_ = [
        ("cb", _DWORD), ("reserved", w.LPWSTR), ("desktop", w.LPWSTR),
        ("title", w.LPWSTR), ("x", _DWORD), ("y", _DWORD), ("x_size", _DWORD),
        ("y_size", _DWORD), ("x_count", _DWORD), ("y_count", _DWORD),
        ("fill", _DWORD), ("flags", _DWORD), ("show", w.WORD),
        ("reserved_size", w.WORD), ("reserved_ptr", _POINTER),
        ("stdin", _HANDLE), ("stdout", _HANDLE), ("stderr", _HANDLE),
    ]


class _Process(c.Structure):
    _fields_ = [
        ("process", _HANDLE), ("thread", _HANDLE), ("pid", _DWORD), ("tid", _DWORD),
    ]


class _StartupEx(c.Structure):
    _fields_ = [("startup", _Startup), ("attributes", _POINTER)]


def _create_bound_suspended(
    kernel: c.WinDLL, exe: str, argv: c.Array[c.c_wchar], env: c.Array[c.c_wchar],
    cwd: str, job: int, proc: _Process, inherited: tuple[int, ...] = (),
) -> bool:
    """Create suspended already inside the fixed job; never fall back to late assignment."""
    initialize = kernel.InitializeProcThreadAttributeList
    initialize.restype, initialize.argtypes = w.BOOL, (_POINTER, _DWORD, _DWORD, c.POINTER(c.c_size_t))
    update = kernel.UpdateProcThreadAttribute
    update.restype, update.argtypes = w.BOOL, (
        _POINTER, _DWORD, c.c_size_t, _POINTER, c.c_size_t, _POINTER, _POINTER,
    )
    delete = kernel.DeleteProcThreadAttributeList
    delete.restype, delete.argtypes = None, (_POINTER,)
    size = c.c_size_t()
    count = 2 if inherited else 1
    if inherited and (len(inherited) != 3 or len(set(inherited)) != 3 or min(inherited) <= 0):
        return False
    initialize(None, count, 0, c.byref(size))
    if not 0 < size.value <= 64 * 1024:
        return False
    raw = c.create_string_buffer(size.value)
    attributes = c.cast(raw, _POINTER)
    if not initialize(attributes, count, 0, c.byref(size)):
        return False
    handles = (_HANDLE * 1)(job)
    private_handles = (_HANDLE * len(inherited))(*inherited)
    startup = _StartupEx()
    startup.startup.cb = c.sizeof(startup)
    startup.attributes = attributes
    try:
        # PROC_THREAD_ATTRIBUTE_JOB_LIST; the handle array stays live until delete.
        if not update(attributes, 0, 0x0002000D, c.byref(handles), c.sizeof(handles), None, None):
            return False
        if inherited and not update(
            attributes, 0, 0x00020002, c.byref(private_handles), c.sizeof(private_handles), None, None,
        ):
            return False
        # Cast the STARTUPINFOEX pointer to the API's declared STARTUPINFO pointer.
        return bool(kernel.CreateProcessW(
            exe, argv, None, None, bool(inherited), 0x08080404,
            env, cwd, c.cast(c.byref(startup), c.POINTER(_Startup)), c.byref(proc),
        ))
    finally:
        delete(attributes)


class _BasicLimits(c.Structure):
    _fields_ = [
        ("process_time", _QWORD), ("job_time", _QWORD), ("flags", _DWORD),
        ("min_working_set", c.c_size_t), ("max_working_set", c.c_size_t),
        ("active_limit", _DWORD), ("affinity", c.c_size_t), ("priority", _DWORD),
        ("scheduling_class", _DWORD),
    ]


class _ExtendedLimits(c.Structure):
    _fields_ = [
        ("basic", _BasicLimits), ("io", _QWORD * 6), ("process_memory", c.c_size_t),
        ("job_memory", c.c_size_t), ("peak_process_memory", c.c_size_t),
        ("peak_job_memory", c.c_size_t),
    ]


class _Accounting(c.Structure):
    _fields_ = [
        ("times", _QWORD * 4), ("page_faults", _DWORD), ("total", _DWORD),
        ("active", _DWORD), ("terminated", _DWORD),
    ]


def _kernel() -> c.WinDLL:
    if os.name != "nt":
        raise Hold("Windows Job Objects are required")
    k = c.WinDLL("kernel32", use_last_error=True)
    # Declare handle widths explicitly; the default int truncates 64-bit handles.
    signatures = {
        "CreateJobObjectW": (_HANDLE, (_POINTER, w.LPCWSTR)),
        "SetInformationJobObject": (w.BOOL, (_HANDLE, c.c_int, _POINTER, _DWORD)),
        "QueryInformationJobObject": (
            w.BOOL, (_HANDLE, c.c_int, _POINTER, _DWORD, c.POINTER(_DWORD)),
        ),
        "CreateProcessW": (
            w.BOOL, (w.LPCWSTR, w.LPWSTR, _POINTER, _POINTER, w.BOOL, _DWORD,
                     _POINTER, w.LPCWSTR, c.POINTER(_Startup), c.POINTER(_Process)),
        ),
        "AssignProcessToJobObject": (w.BOOL, (_HANDLE, _HANDLE)),
        "ResumeThread": (_DWORD, (_HANDLE,)),
        "TerminateProcess": (w.BOOL, (_HANDLE, w.UINT)),
        "TerminateJobObject": (w.BOOL, (_HANDLE, w.UINT)),
        "WaitForSingleObject": (_DWORD, (_HANDLE, _DWORD)),
        "CloseHandle": (w.BOOL, (_HANDLE,)),
    }
    for name, (restype, argtypes) in signatures.items():
        fn = getattr(k, name)
        fn.restype = restype
        fn.argtypes = argtypes
    return k



class _OwnedWindowsJob:
    """Single native owner shared by the fixed vendor role and inert fixture."""

    def __init__(self, clock: Callable[[], int]) -> None:
        self._clock = clock
        self._k: c.WinDLL | None = None
        self._job: int | None = None
        self._process: int | None = None
        self._assigned = False
        self._attempted = False
        self._terminal: bool | None = None

    def _start_owned(
        self, path: Path, args: list[str], environment: dict[str, str], deadline_ms: int,
        *, before_resume: Callable[[int, int], None] | None = None,
        bind_at_creation: bool = False,
        inherited: tuple[int, ...] = (),
    ) -> bool:
        if self._attempted or self._terminal is not None or (inherited and not bind_at_creation):
            return False
        self._attempted = True
        k = _kernel()
        self._k = k
        system_root = os.environ.get("SystemRoot")
        if not system_root or not Path(system_root).is_absolute():
            raise Hold("Windows root unavailable")
        env = c.create_unicode_buffer("\0".join(
            f"{key}={value}" for key, value in sorted(
                (environment | {"SystemRoot": system_root}).items(), key=lambda pair: pair[0].casefold(),
            )
        ) + "\0\0")
        exe = str(path)
        argv = c.create_unicode_buffer(subprocess.list2cmdline([exe, *args]))
        startup = _Startup()
        startup.cb = c.sizeof(startup)
        proc = _Process()
        self._job = k.CreateJobObjectW(None, None)
        if not self._job:
            return False
        limits = _ExtendedLimits()
        limits.basic.flags = 0x2000  # Kill on close; no breakaway.
        if not k.SetInformationJobObject(self._job, 9, c.byref(limits), c.sizeof(limits)):
            return False
        remaining(self._clock, deadline_ms)
        if bind_at_creation:
            created = _create_bound_suspended(k, exe, argv, env, str(path.parent), self._job, proc, inherited)
        else:
            created = bool(k.CreateProcessW(
                exe, argv, None, None, False, 0x08000404,
                env, str(path.parent), c.byref(startup), c.byref(proc),
            ))
        if not created:
            return False
        self._process = proc.process
        try:
            if not bind_at_creation and not k.AssignProcessToJobObject(self._job, self._process):
                return False
            self._assigned = True
            if before_resume is not None:
                before_resume(self._job, self._process)
            remaining(self._clock, deadline_ms)
            return int(k.ResumeThread(proc.thread)) == 1
        finally:
            k.CloseHandle(proc.thread)

    def request_stop(self, deadline_ms: int) -> None:
        k = self._k
        if k is not None and self._process:
            if self._assigned:
                k.TerminateJobObject(self._job, 1)
            elif k.WaitForSingleObject(self._process, 0) != 0:
                k.TerminateProcess(self._process, 1)

    def confirmed_quiescent(self, deadline_ms: int) -> bool:
        if self._terminal is not None:
            return self._terminal
        k = self._k
        try:
            if k is None:
                self._terminal = self._process is None and self._clock() <= deadline_ms
                return self._terminal
            accounting = _Accounting()
            while self._clock() <= deadline_ms:
                exited = self._process is None or k.WaitForSingleObject(self._process, 0) == 0
                empty = not self._job or (
                    bool(k.QueryInformationJobObject(self._job, 1, c.byref(accounting), c.sizeof(accounting), None))
                    and accounting.active == 0
                )
                if exited and empty:
                    self._terminal = True
                    return True
                time.sleep(min(0.01, remaining(self._clock, deadline_ms)))
            return False
        finally:
            if self._terminal is None:
                self._terminal = False
            self._close_owned_handles()

    def _handoff_exact_handles(self) -> tuple[int, int]:
        """Move an already-owned live Job/root pair; its original object is sealed."""
        if not self._attempted or not self._assigned or not self._job or not self._process or self._terminal is not None:
            raise Hold("owned role handoff unavailable")
        job, process = self._job, self._process
        self._job = self._process = None
        self._terminal = False
        return job, process

    def _close_owned_handles(self) -> None:
        job, process = self._job, self._process
        self._job = self._process = None
        k = self._k
        if k is not None:
            if job:
                k.CloseHandle(job)
            if process:
                if self._terminal is not True and not self._assigned and k.WaitForSingleObject(process, 0) != 0:
                    k.TerminateProcess(process, 1)
                k.CloseHandle(process)


class RuntimeRole(_OwnedWindowsJob):
    """One retained Windows job and process, assigned prior to resume."""

    def __init__(
        self, path: Path, packet: Packet, bearer: str, platform_key: str, clock: Callable[[], int],
    ) -> None:
        if (
            not path.is_absolute() or path.name != "tunnel-client-runtime.exe"
            or not re.fullmatch(r"tunnel_(?:[a-z0-9]{4}_)?[a-z0-9]{32}", packet.tunnel)
            or not re.fullmatch(r"org-[A-Za-z0-9]{1,128}", packet.platform)
            or not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", bearer)
            or not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", platform_key)
        ):
            raise Hold("invalid fixed runtime binding")
        self._path = path
        self._digest = packet.runtime_binary_digest
        self._environment = {
            "CONTROL_PLANE_API_KEY": platform_key,
            "LIGHTHOUSE_T02_LOOPBACK_AUTH": "Bearer " + bearer,
        }
        self._args = [
            "run", "--control-plane.tunnel-id", packet.tunnel,
            "--control-plane.organization-id", packet.platform,
            "--control-plane.poll-channel", "main",
            "--mcp.server-url", "http://127.0.0.1:8765/mcp",
            "--mcp.extra-headers", "Authorization: env:LIGHTHOUSE_T02_LOOPBACK_AUTH",
            "--mcp.discovery-extra-headers", "Authorization: env:LIGHTHOUSE_T02_LOOPBACK_AUTH",
            "--mcp.oauth-discovery", "disabled", "--health.listen-addr", "127.0.0.1:0",
            "--log.level", "warn",
        ]
        super().__init__(clock)
        self._candidate_checked = False

    def verified_digest(self, deadline: int) -> str:
        """Read the existing candidate bytes, no subprocess or version probe."""
        remaining(self._clock, deadline)
        if self._path.resolve(strict=True) != self._path or not self._path.is_file():
            raise Hold("runtime must be the existing pinned local file")
        digest = hashlib.sha256()
        with self._path.open("rb") as handle:
            for _ in range(128):
                remaining(self._clock, deadline)
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    return digest.hexdigest()
                digest.update(chunk)
        raise Hold("runtime binary outside size bound")

    def start(self, deadline_ms: int) -> bool:
        if self._candidate_checked or self._terminal is not None:
            return False
        self._candidate_checked = True
        if self.verified_digest(deadline_ms) != self._digest:
            return False
        return self._start_owned(self._path, self._args, self._environment, deadline_ms)
