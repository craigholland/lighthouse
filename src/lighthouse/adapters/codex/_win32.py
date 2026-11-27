"""Narrow CPython 3.14 Windows pipe and Job binding for one isolated review."""

from __future__ import annotations

import ctypes as c
import os
import subprocess
from ctypes import wintypes as w
from importlib import import_module
from pathlib import Path
from time import monotonic, sleep
from typing import Any


class _Accounting(c.Structure):
    _fields_ = [("times", c.c_longlong * 4), ("faults", w.DWORD), ("total", w.DWORD),
                ("active", w.DWORD), ("terminated", w.DWORD)]


class _Limits(c.Structure):
    _fields_ = [("times", c.c_longlong * 2), ("flags", w.DWORD),
                ("working_min", c.c_size_t), ("working_max", c.c_size_t), ("limit", w.DWORD),
                ("affinity", c.c_size_t), ("priority", w.DWORD), ("scheduling", w.DWORD)]


class _Extended(c.Structure):
    _fields_ = [("basic", _Limits), ("io", c.c_ulonglong * 6), ("memory", c.c_size_t * 4)]


class WinChild:
    """Own the retained root and Job and only the three isolated child pipe capabilities."""

    def __init__(self) -> None:
        if os.name != "nt":
            raise OSError("Windows review process unavailable")
        self._api = import_module("_winapi")
        self._pipe = import_module("asyncio.windows_utils").pipe
        self._kernel = c.WinDLL("kernel32", use_last_error=True)
        for name, result, args in (
            ("CreateJobObjectW", w.HANDLE, (c.c_void_p, w.LPCWSTR)),
            ("SetInformationJobObject", w.BOOL, (w.HANDLE, w.DWORD, c.c_void_p, w.DWORD)),
            ("QueryInformationJobObject", w.BOOL, (w.HANDLE, w.DWORD, c.c_void_p, w.DWORD, c.c_void_p)),
            ("AssignProcessToJobObject", w.BOOL, (w.HANDLE, w.HANDLE)),
            ("TerminateJobObject", w.BOOL, (w.HANDLE, w.UINT)),
            ("ResumeThread", w.DWORD, (w.HANDLE,)),
        ):
            fn = getattr(self._kernel, name)
            fn.restype, fn.argtypes = result, args
        self._job: int | None = None
        self._root: int | None = None
        self._assigned = False
        self._handles: list[int] = []
        self._stdin = self._stdout = self._stderr = 0
        self._error_read: Any = None
        self._stderr_drained = False
        self._pending: list[Any] = []

    @staticmethod
    def _expect(ok: object) -> None:
        if not ok:
            raise OSError("owned Windows operation failed")

    def start(self, executable: Path, args: tuple[str, ...], cwd: Path, env: dict[str, str], deadline: float) -> None:
        if self._job is not None or not monotonic() < deadline:
            raise TimeoutError("review startup unavailable")
        self._job = self._kernel.CreateJobObjectW(None, None)
        self._expect(self._job)
        limits = _Extended()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE, no breakaway.
        self._expect(self._kernel.SetInformationJobObject(self._job, 9, c.byref(limits), c.sizeof(limits)))
        child_handles = []
        for flags in ((False, True), (True, False), (True, False)):
            read, write = self._pipe(overlapped=flags, bufsize=65536)
            self._handles.extend((read, write))
            child_handles.append(write if flags[0] else read)
        self._stdin, self._stdout, self._stderr = self._handles[1], self._handles[2], self._handles[4]
        for handle in child_handles:
            os.set_handle_inheritable(handle, True)
        startup = subprocess.STARTUPINFO(
            dwFlags=subprocess.STARTF_USESTDHANDLES, hStdInput=child_handles[0],
            hStdOutput=child_handles[1], hStdError=child_handles[2],
            lpAttributeList={"handle_list": child_handles},
        )
        binary = str(executable)
        if not monotonic() < deadline:
            raise TimeoutError("review startup deadline elapsed")
        self._root, thread, _, _ = self._api.CreateProcess(
            binary, subprocess.list2cmdline([binary, *args]), None, None, True,
            0x08000404, env, str(cwd), startup,
        )
        try:
            self._expect(self._kernel.AssignProcessToJobObject(self._job, self._root))
            self._assigned = True
            for handle in child_handles:
                self._close(handle)
            if not monotonic() < deadline:
                raise TimeoutError("review startup deadline elapsed")
            self._expect(self._kernel.ResumeThread(thread) == 1)
        finally:
            self._api.CloseHandle(thread)

    def _close(self, handle: int) -> None:
        self._api.CloseHandle(handle)
        self._handles.remove(handle)

    def _pump_error(self) -> None:
        """Discard private stderr, capped per overlapped read; never merge into stdout."""
        if self._stderr_drained:
            return
        try:
            if self._error_read is None:
                self._error_read, _ = self._api.ReadFile(self._stderr, 8192, overlapped=True)
            if self._api.WaitForSingleObject(self._error_read.event, 0) == 0:
                _, error = self._error_read.GetOverlappedResult(False)
                self._error_read = None
                self._stderr_drained = error != 0
        except OSError as exc:
            if getattr(exc, "winerror", None) not in (38, 109, 232, 233):
                raise
            self._stderr_drained = True

    def _finish(self, op: Any, deadline: float) -> int:
        pending = True
        try:
            while monotonic() < deadline:
                self._pump_error()
                budget = min(10, max(0, int((deadline - monotonic()) * 1000)))
                if self._api.WaitForSingleObject(op.event, budget) == 0:
                    pending = False
                    count, error = op.GetOverlappedResult(False)
                    if not error and monotonic() < deadline:
                        return int(count)
                    if error in (38, 109, 232, 233):
                        return 0
                    if not error:
                        break
                    raise OSError("owned Windows pipe result unavailable")
            raise TimeoutError("owned Windows pipe deadline elapsed")
        finally:
            if pending:
                self._pending.append(op)
                try:
                    op.cancel()
                except OSError:
                    pass

    def read(self, size: int, deadline: float) -> bytes | None:
        if not monotonic() < deadline:
            raise TimeoutError("review read deadline elapsed")
        try:
            op, _ = self._api.ReadFile(self._stdout, size, overlapped=True)
            count = self._finish(op, deadline)
            return bytes(op.getbuffer()[:count]) if count else None
        except OSError as exc:
            if getattr(exc, "winerror", None) in (38, 109, 232, 233):
                return None
            raise

    def write(self, data: bytes, deadline: float) -> int:
        if not monotonic() < deadline:
            raise TimeoutError("review write deadline elapsed")
        op, _ = self._api.WriteFile(self._stdin, data, overlapped=True)
        return self._finish(op, deadline)

    def terminate(self) -> None:
        if self._stdin and self._stdin in self._handles:
            self._close(self._stdin)
        if self._assigned:
            self._expect(self._kernel.TerminateJobObject(self._job, 1))
        elif self._root is not None:
            self._api.TerminateProcess(self._root, 1)  # Only our never-resumed root.

    def active_count(self) -> int:
        info = _Accounting()
        self._expect(self._kernel.QueryInformationJobObject(self._job, 1, c.byref(info), c.sizeof(info), None))
        return int(info.active)

    def witnesses(self, deadline: float) -> tuple[bool, bool]:
        while self._root is not None and monotonic() < deadline:
            root = self._api.WaitForSingleObject(self._root, 0) == 0
            empty = self._job is not None and self.active_count() == 0
            if root and empty:
                return True, True
            sleep(min(0.005, max(0, deadline - monotonic())))
        return False, False

    def close(self, deadline: float) -> None:
        """Close owned handles once; finish cancellation before reporting clean."""
        bad = False
        job, root = self._job, self._root
        self._job = self._root = None
        self._assigned = False
        # Closing the owned Job is an emergency safety net, never a cleanup witness.
        for handle in (job, root):
            if handle is not None:
                try:
                    self._api.CloseHandle(handle)
                except OSError:
                    bad = True
        if self._error_read is not None:
            self._pending.append(self._error_read)
            self._error_read = None
        for op in self._pending:
            try:
                op.cancel()
            except OSError:
                pass
        for handle in self._handles[:]:
            try:
                self._close(handle)
            except OSError:
                bad = True
        for op in self._pending[:]:
            budget = max(0, int((deadline - monotonic()) * 1000))
            if self._api.WaitForSingleObject(op.event, budget) != 0:
                bad = True
                continue
            try:
                op.GetOverlappedResult(False)
            except OSError:
                pass
            self._pending.remove(op)
        if bad:
            raise OSError("owned process or pipe cleanup not confirmed")

    def emergency_close(self, deadline: float) -> None:
        """Only for the fixed fixture's bounded emergency teardown."""
        try:
            self.terminate()
        finally:
            self.close(deadline)
