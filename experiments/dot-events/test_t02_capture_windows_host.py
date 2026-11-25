"""Mock the Windows ABI boundary; no process or actual Win32 call."""

import ctypes as c
from pathlib import Path
from unittest.mock import Mock

import pytest
import t02_event_windows as windows
from t02_capture_windows_host import CaptureSupervisorHost


@pytest.mark.parametrize("allow_attribute", [True, False])
def test_fixed_host_is_job_bound_before_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, allow_attribute: bool,
) -> None:
    kernel = Mock()
    trace: list[str] = []
    kernel.CreateJobObjectW.return_value = 11
    kernel.ResumeThread.return_value = 1
    kernel.WaitForSingleObject.return_value = 0
    kernel.QueryInformationJobObject.return_value = True

    def init(ptr: object, count: int, _flags: int, size_ptr: object) -> bool:
        assert count == 1
        if ptr is None:
            getattr(size_ptr, "_obj").value = 64
            return False
        trace.append("init")
        return True

    def update(
        _ptr: object, _flags: int, attribute: int, handles: object, size: int, *_unused: object,
    ) -> bool:
        assert attribute == 0x0002000D and size == c.sizeof(c.c_void_p)
        assert getattr(handles, "_obj")[0] == 11
        trace.append("job-bound")
        return allow_attribute

    def create(*args: object) -> bool:
        assert args[4] is False  # No inherited handles.
        assert args[5] == 0x08080404  # Suspended, extended startup, no window.
        assert "-I" in getattr(args[1], "value")
        assert "t02_capture_supervisor.py" in getattr(args[1], "value")
        assert getattr(args[1], "value").count("t02_capture_supervisor.py") == 1
        proc = getattr(args[-1], "_obj")
        proc.process = 22
        proc.thread = 33
        trace.append("create")
        return True

    kernel.InitializeProcThreadAttributeList.side_effect = init
    kernel.UpdateProcThreadAttribute.side_effect = update
    kernel.CreateProcessW.side_effect = create
    kernel.DeleteProcThreadAttributeList.side_effect = lambda _: trace.append("delete")
    def resume(_handle: int) -> int:
        trace.append("resume")
        return 1

    kernel.ResumeThread.side_effect = resume
    monkeypatch.setattr(windows, "_kernel", lambda: kernel)
    monkeypatch.setenv("SystemRoot", str(tmp_path))
    role = CaptureSupervisorHost(tmp_path / "python.exe", lambda: 1)
    assert role.start(100) is allow_attribute
    assert not role.start(100)
    kernel.AssignProcessToJobObject.assert_not_called()
    if allow_attribute:
        assert trace == ["init", "job-bound", "create", "delete", "resume"]
        role.request_stop(100)
        kernel.TerminateJobObject.assert_called_once_with(11, 1)
    else:
        assert trace == ["init", "job-bound", "delete"]
        kernel.CreateProcessW.assert_not_called()
        kernel.ResumeThread.assert_not_called()
    assert role.confirmed_quiescent(100)
    expected = {11, 22, 33} if allow_attribute else {11}
    assert {call.args[0] for call in kernel.CloseHandle.call_args_list} == expected
