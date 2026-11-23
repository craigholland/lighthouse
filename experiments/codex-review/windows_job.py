"""Win32 containment for the fixed, harmless offline test fixture only."""

import ctypes as c
import os
import subprocess
import sys
import time
from ctypes import wintypes as w
from pathlib import Path

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
        raise RuntimeError("Windows Job Objects are required.")
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


class FixtureJob:
    """Own a single test job; never accepts a caller command or process ID."""

    def __init__(self) -> None:
        self._k = _kernel()
        self._job: int | None = None
        self._process: int | None = None

    def start(self) -> None:
        """Start the sibling Python fixture suspended; assign before resuming it."""
        if self._job is not None:
            raise RuntimeError("Fixture job already opened.")
        executable = str(Path(sys.executable).resolve(strict=True))
        fixture = str(Path(__file__).with_name("job_fixture.py").resolve(strict=True))
        argv = c.create_unicode_buffer(subprocess.list2cmdline([executable, "-I", fixture]))
        env = c.create_unicode_buffer(
            "SystemRoot=" + os.environ["SystemRoot"] + "\0\0"
        )
        startup = _Startup()
        startup.cb = c.sizeof(startup)
        process = _Process()
        self._job = self._k.CreateJobObjectW(None, None)
        if not self._job:
            raise RuntimeError("Could not create fixture job.")
        limits = _ExtendedLimits()
        limits.basic.flags = 0x2000  # KILL_ON_JOB_CLOSE; no breakaway flags.
        try:
            if not self._k.SetInformationJobObject(
                self._job, 9, c.byref(limits), c.sizeof(limits)
            ):
                raise RuntimeError("Could not set fixture job limits.")
            if not self._k.CreateProcessW(
                executable, argv, None, None, False, 0x08000404,
                env, None, c.byref(startup), c.byref(process),
            ):
                raise RuntimeError("Could not create suspended fixture.")
            self._process = process.process
            try:
                if not self._k.AssignProcessToJobObject(self._job, self._process):
                    self._k.TerminateProcess(self._process, 1)
                    self._k.WaitForSingleObject(self._process, 2000)
                    raise RuntimeError("Fixture containment failed; never resumed.")
                if self._k.ResumeThread(process.thread) == 0xFFFFFFFF:
                    raise RuntimeError("Could not resume contained fixture.")
            finally:
                self._k.CloseHandle(process.thread)
        except BaseException:
            self.close()
            raise

    def active_count(self) -> int:
        """Read native accounting, not a prediction from the worker exit."""
        accounting = _Accounting()
        if not self._job or not self._k.QueryInformationJobObject(
            self._job, 1, c.byref(accounting), c.sizeof(accounting), None
        ):
            raise RuntimeError("Could not observe fixture job accounting.")
        return int(accounting.active)

    def force(self) -> None:
        """Terminate only the process tree belonging to this owned test job."""
        if not self._job or not self._k.TerminateJobObject(self._job, 1):
            raise RuntimeError("Could not terminate owned fixture job.")

    def wait_quiescent(self, seconds: float) -> bool:
        """Require both retained worker-handle signal and zero active descendants."""
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if not self._process:
                return False
            state = self._k.WaitForSingleObject(self._process, 0)
            if state not in (0, 258):
                raise RuntimeError("Could not observe fixture worker handle.")
            if state == 0 and self.active_count() == 0:
                return True
            time.sleep(0.01)
        return False

    def close(self) -> None:
        """Release handles; kill-on-close is fail-safe, not a shutdown receipt."""
        if self._job:
            self._k.CloseHandle(self._job)
            self._job = None
        if self._process:
            self._k.CloseHandle(self._process)
            self._process = None
