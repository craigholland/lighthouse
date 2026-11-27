"""Bounded owned session tests; real Windows fixture is separately opted in."""

import os
import sys
from collections import deque
from pathlib import Path
from time import monotonic
from types import SimpleNamespace

import pytest

from lighthouse.adapters.codex._win32 import WinChild
from lighthouse.adapters.codex.windows_session import WindowsSession


class ByteChild:
    def __init__(self, chunks: tuple[bytes, ...], *, witnesses=(True, True)) -> None:
        self.parts = deque(chunks)
        self.sent = bytearray()
        self.witnesses_value = witnesses
        self.stopped = self.closed = False

    def read(self, count: int, _deadline: float) -> bytes | None:
        if not self.parts:
            return None
        block = self.parts.popleft()
        if block[count:]:
            self.parts.appendleft(block[count:])
        return block[:count]

    def write(self, data: bytes, _deadline: float) -> int:
        block = data[:3]
        self.sent += block
        return len(block)

    def terminate(self):
        self.stopped = True

    def witnesses(self, _deadline: float):
        assert self.stopped
        return self.witnesses_value

    def close(self, _deadline: float):
        self.closed = True


def test_contiguous_partial_reads_and_writes_with_final_drain() -> None:
    child = ByteChild((b'{"o', b'k":1}\n{"last":2}\n'))
    session = WindowsSession(child, 3.0, lambda: 0.0)
    session.write(b'{"msg":1}\n', 2.0)
    assert child.sent == b'{"msg":1}\n'
    assert session.read(128, 2.0) == b'{"ok":1}\n'
    receipt = session.shutdown(3.0)
    assert (receipt.root_exited, receipt.contained_empty, receipt.frames) == (True, True, (b'{"last":2}\n',))
    assert child.closed


@pytest.mark.parametrize(("chunks", "witnesses"), [
    ((b"partial",), (True, True)),
    ((b"x" * 1_048_576,), (True, True)),
    ((b"good\n",), (True, False)),
    ((b"good\n",), (False, True)),
])
def test_partial_or_missing_witness_never_confirms_cleanup(chunks, witnesses) -> None:
    child = ByteChild(chunks, witnesses=witnesses)
    session = WindowsSession(child, 3.0, lambda: 0.0)
    receipt = session.shutdown(3.0)
    assert not (receipt.root_exited and receipt.contained_empty) and receipt.frames == ()
    assert child.closed


_SCRIPT = (
    "import subprocess,sys,time;"
    "subprocess.Popen([sys.executable,'-I','-c','import time; time.sleep(12)'],"
    "stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,"
    "creationflags=subprocess.CREATE_NO_WINDOW);"
    "sys.stdout.buffer.write(b'{\"ready\":true}\\n');sys.stdout.flush();time.sleep(12)"
)


@pytest.mark.skipif(
    os.name != "nt" or os.environ.get("LIGHTHOUSE_T07_OWNED_FIXTURE") != "1",
    reason="requires separate approval for the fixed harmless Windows fixture",
)
def test_owned_windows_python_fixture(tmp_path: Path) -> None:
    """Normal and stalled stdin, sequential, own root+descendant only, fail-stop."""
    executable = Path(sys._base_executable).resolve(strict=True)
    assert executable.name.casefold() == "python.exe"
    common = {"SystemRoot": os.environ["SystemRoot"], "TEMP": str(tmp_path)}
    for stalled in (False, True):
        start = monotonic()
        owned = WinChild()
        session = WindowsSession(owned, start + 10)
        confirmed = False
        try:
            owned.start(executable, ("-I", "-c", _SCRIPT), tmp_path, common, start + 3)
            assert session.read(128, start + 5) == b'{"ready":true}\n'
            assert owned.active_count() >= 2, "owned Job did not witness both fixed stand-ins"
            if stalled:
                with pytest.raises(TimeoutError, match="pipe deadline"):
                    session.write(b"x" * 4_194_303 + b"\n", min(start + 7, monotonic() + 0.4))
            receipt = session.shutdown(start + 10)
            confirmed = receipt.root_exited and receipt.contained_empty
            assert confirmed, "owned root/Job completion unconfirmed"
            assert monotonic() < start + 10
            print("stalled: present-two/root-exited/Job-empty" if stalled
                  else "normal: present-two/root-exited/Job-empty", flush=True)
        finally:
            if not confirmed:
                owned.emergency_close(start + 13)


@pytest.mark.parametrize("assignment", [True, False])
def test_native_boundary_assigns_before_resume_and_never_uses_other_handles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, assignment: bool,
) -> None:
    trace = []
    created = iter(((11, 12), (13, 14), (15, 16)))
    owned = WinChild.__new__(WinChild)
    owned._handles = []
    owned._job = owned._root = None
    owned._assigned = False
    owned._stdin = owned._stdout = owned._stderr = 0
    owned._error_read = None
    owned._pending = []
    owned._pipe = lambda **_: next(created)
    monkeypatch.setattr(os, "set_handle_inheritable", lambda h, b: trace.append(("inherit", h, b)))

    def create(binary, argv, _pa, _ta, inherit, flags, env, cwd, startup):
        assert inherit is True and flags & 4
        assert startup.lpAttributeList == {"handle_list": [11, 14, 16]}
        assert env == {"SystemRoot": "synthetic"} and binary.endswith("python.exe")
        trace.append("create-suspended")
        return 21, 22, 100, 101

    owned._api = SimpleNamespace(
        CreateProcess=create, CloseHandle=lambda h: trace.append(("close", h)),
        TerminateProcess=lambda h, code: trace.append(("terminate-unresumed", h)),
    )
    owned._kernel = SimpleNamespace(
        CreateJobObjectW=lambda *_: 23,
        SetInformationJobObject=lambda *_: True,
        AssignProcessToJobObject=lambda job, root: trace.append(("assign", job, root)) or assignment,
        TerminateJobObject=lambda job, _: trace.append(("terminate-job", job)) or True,
        ResumeThread=lambda thread: trace.append(("resume", thread)) or 1,
    )
    if assignment:
        owned.start(tmp_path / "python.exe", (), tmp_path, {"SystemRoot": "synthetic"}, monotonic() + 5)
        assert trace.index(("assign", 23, 21)) < trace.index(("resume", 22))
    else:
        with pytest.raises(OSError, match="owned Windows operation failed"):
            owned.start(tmp_path / "python.exe", (), tmp_path, {"SystemRoot": "synthetic"}, monotonic() + 5)
        assert ("resume", 22) not in trace
    owned.emergency_close(monotonic() + 5)
    assert (("terminate-job", 23) in trace) is assignment
    assert (("terminate-unresumed", 21) in trace) is not assignment
    assert all(trace.count(("close", h)) == 1 for h in (11, 12, 13, 14, 15, 16, 21, 22, 23))
