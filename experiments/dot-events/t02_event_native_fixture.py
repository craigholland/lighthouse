"""Fixed Python-only Windows ownership fixture; never loads the vendor."""

from __future__ import annotations

import ctypes as c
import json
import os
import subprocess
import sys
import time
from ctypes import wintypes as w
from pathlib import Path
from typing import cast

from t02_event_windows import _OwnedWindowsJob

_FIXTURE = Path(__file__).resolve()
_BOOTSTRAP = ("import runpy,sys;sys.path.insert(0,sys.argv.pop(1));"
              "runpy.run_path(sys.argv.pop(1),run_name=\x27__main__\x27)")


def _ms() -> int:
    return time.monotonic_ns() // 1_000_000


def _api() -> c.WinDLL:
    k = c.WinDLL("kernel32", use_last_error=True)
    for name, returns, args in (
        ("GetProcessId", w.DWORD, (w.HANDLE,)),
        ("OpenProcess", w.HANDLE, (w.DWORD, w.BOOL, w.DWORD)),
        ("IsProcessInJob", w.BOOL, (w.HANDLE, w.HANDLE, c.POINTER(w.BOOL))),
        ("WaitForSingleObject", w.DWORD, (w.HANDLE, w.DWORD)),
        ("CloseHandle", w.BOOL, (w.HANDLE,)),
    ):
        f = getattr(k, name)
        f.restype, f.argtypes = returns, args
    return k


def witness(k: c.WinDLL, pid: int) -> int:
    handle = cast(int, k.OpenProcess(0x101000, False, pid))  # SYNCHRONIZE, QUERY_LIMITED_INFORMATION
    if not handle:
        raise RuntimeError("fixture witness handle unavailable")
    return handle


def _wait_file(path: Path, deadline: int) -> str:
    while _ms() < deadline:
        if path.is_file():
            return path.read_text(encoding="ascii")
        time.sleep(0.01)
    raise RuntimeError("native fixture witness deadline")


def _publish(path: Path, value: object) -> None:
    scratch = path.with_suffix(".part")
    scratch.write_text(json.dumps(value), encoding="ascii")
    scratch.replace(path)


def _owner(directory: Path, case: str) -> None:
    k = _api()
    role = _OwnedWindowsJob(_ms)
    deadline = _ms() + 12_000

    def no_fixture_work_before_resume(job: int, root: int) -> None:
        assigned = w.BOOL()
        if (
            not k.IsProcessInJob(root, job, c.byref(assigned)) or not assigned.value
            or k.WaitForSingleObject(root, 0) != 258 or (directory / "tree.json").exists()
        ):
            raise RuntimeError("fixture did not remain suspended until assigned")

    try:
        if not role._start_owned(
            Path(sys.executable).resolve(strict=True),
            ["-I", "-c", _BOOTSTRAP, str(_FIXTURE.parent), str(_FIXTURE), "tree", str(directory)], {}, deadline - 6000,
            before_resume=no_fixture_work_before_resume,
        ):
            raise RuntimeError("fixed harmless fixture could not start")
        if role._process is None or role._job is None:
            raise RuntimeError("fixture owner handles unavailable")
        root_pid, leaf_pid = json.loads(_wait_file(directory / "tree.json", deadline - 6000))
        if k.GetProcessId(role._process) != root_pid:
            raise RuntimeError("root not owned")
        leaf = witness(k, leaf_pid)
        try:
            assigned = w.BOOL()
            if not k.IsProcessInJob(leaf, role._job, c.byref(assigned)) or not assigned.value:
                raise RuntimeError("descendant not in the same owned job")
            _publish(directory / "owned.json", [root_pid, leaf_pid])
            if _wait_file(directory / "release.json", deadline - 2500) != '"release"':
                raise RuntimeError("invalid fixture control")
            if case == "owner-loss":
                # Kernel closes the sole job handle as this supervisor exits.
                # Its parent has separate handles to the exact two owned children.
                os._exit(0)
            role.request_stop(deadline)
            if not role.confirmed_quiescent(deadline):
                raise RuntimeError("explicit fixture shutdown unconfirmed")
            if not role.confirmed_quiescent(deadline):
                raise RuntimeError("confirmed state changed")
            role.request_stop(deadline)
        finally:
            k.CloseHandle(leaf)
    finally:
        role.request_stop(deadline)
        role.confirmed_quiescent(deadline)


def _tree(directory: Path) -> None:
    k = _api()
    # The child must see itself in a job before it can publish any fixture work.
    assigned = w.BOOL()
    get_current = k.GetCurrentProcess
    get_current.restype = w.HANDLE
    if not k.IsProcessInJob(get_current(), None, c.byref(assigned)) or not assigned.value:
        raise RuntimeError("fixture work started outside a job")
    leaf = subprocess.Popen(
        [sys.executable, "-I", "-c", _BOOTSTRAP, str(_FIXTURE.parent), str(_FIXTURE), "leaf", str(directory)], close_fds=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    try:
        _publish(directory / "tree.json", [os.getpid(), leaf.pid])
        time.sleep(16)
    finally:
        if leaf.poll() is None:
            leaf.kill()
        leaf.wait(timeout=2)


def _entry() -> None:
    args = sys.argv[1:]
    if len(args) not in (2, 3):
        raise RuntimeError("invalid inert fixture command")
    kind, target, *rest = args
    directory = Path(target).resolve(strict=True)
    if not directory.is_dir() or not directory.name.startswith("native-t02-"):
        raise RuntimeError("only disposable native test directory accepted")
    if kind == "owner" and rest in (["explicit"], ["owner-loss"]):
        _owner(directory, rest[0])
    elif kind == "tree" and not rest:
        _tree(directory)
    elif kind == "leaf" and not rest:
        time.sleep(18)
    else:
        raise RuntimeError("invalid inert fixture role")


if __name__ == "__main__":
    _entry()
