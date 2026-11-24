"""Win32 containment for fixed Lighthouse child roles and the offline fixture."""

import ctypes as c
import os
import subprocess
import sys
import sysconfig
import time
from ctypes import wintypes as w
from pathlib import Path
from typing import Literal

from supervisor import Role

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


class _OwnedProcess:
    """Own one job and its process handle; never accepts a process ID."""

    def __init__(self) -> None:
        self._k = _kernel()
        self._job: int | None = None
        self._process: int | None = None
        self._assigned = False

    def _start(
        self, arguments: list[str], environment: dict[str, str], *, interpreter: str = sys.executable,
    ) -> None:
        """Create suspended, assign to this job, and only then resume."""
        if self._job is not None:
            raise RuntimeError("Job already opened.")
        executable = str(Path(interpreter).resolve(strict=True))
        argv = c.create_unicode_buffer(subprocess.list2cmdline([executable, *arguments]))
        if any(
            "=" in key or not key or "\0" in key + value
            for key, value in environment.items()
        ):
            raise RuntimeError("Invalid isolated child environment.")
        block = "\0".join(
            f"{key}={environment[key]}" for key in sorted(environment, key=str.casefold)
        )
        env = c.create_unicode_buffer(block + "\0\0")
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
                    raise RuntimeError("Owned worker containment failed; never resumed.")
                self._assigned = True
                if self._k.ResumeThread(process.thread) == 0xFFFFFFFF:
                    raise RuntimeError("Could not resume contained fixture.")
            finally:
                self._k.CloseHandle(process.thread)
        except BaseException:
            # A partial start remains visible to supervisor cleanup.
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
        if self._process and not self._assigned:
            if not self.worker_exited() and not self._k.TerminateProcess(self._process, 1):
                raise RuntimeError("Could not terminate the owned suspended worker.")
            return
        if not self._job or not self._k.TerminateJobObject(self._job, 1):
            raise RuntimeError("Could not terminate owned job.")

    def wait_quiescent(self, seconds: float) -> bool:
        """Require both retained worker-handle signal and zero active descendants."""
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if self.worker_exited() and self.active_count() == 0:
                return True
            time.sleep(0.01)
        return False

    def worker_exited(self) -> bool:
        """Observe the retained worker handle without a blocking wait."""
        if self._process is None:
            return False
        result = int(self._k.WaitForSingleObject(self._process, 0))
        if result not in (0, 258):
            raise RuntimeError("Could not observe worker handle.")
        return result == 0

    def close(self) -> None:
        """Release handles; kill-on-close is fail-safe, not a shutdown receipt."""
        if self._job:
            self._k.CloseHandle(self._job)
            self._job = None
        if self._process:
            if not self._assigned:
                self._k.TerminateProcess(self._process, 1)
            self._k.CloseHandle(self._process)
            self._process = None



class FixtureJob(_OwnedProcess):
    """The native test can start only the fixed harmless sibling fixture."""

    def start(self) -> None:
        """Start the proof-owned Python-only fixture."""
        fixture = str(Path(__file__).with_name("job_fixture.py").resolve(strict=True))
        self._start(["-I", fixture], {"SystemRoot": os.environ["SystemRoot"]})


class StageJob(_OwnedProcess):
    """A fixed experiment worker, with an explicit role-specific environment."""

    def start(self, role: Role | Literal["reverify"], control: Path, environment: dict[str, str]) -> None:
        """Launch a known Lighthouse stage, not a configurable command."""
        script = Path(__file__).with_name("live_stage.py").resolve(strict=True)
        bootstrap = (
            "import runpy,sys;sys.path.insert(0,sys.argv.pop(1));"
            "sys.path.insert(1,sys.argv.pop(1));"
            "runpy.run_path(sys.argv.pop(1),run_name='__main__')"
        )
        base_interpreter = getattr(sys, "_base_executable", None)
        if not isinstance(base_interpreter, str) or not base_interpreter:
            raise RuntimeError("Installed base interpreter unavailable.")
        self._start(
            ["-I", "-c", bootstrap, str(script.parent), sysconfig.get_path("purelib"),
             str(script), str(role), str(control)],
            environment, interpreter=base_interpreter,
        )
