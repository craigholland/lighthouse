"""Test native pipe and role ownership with synthetic handles and no Win32 I/O."""

import struct
from unittest.mock import Mock

import pytest
import t02_capture_role_handles as role_handles
from t02_capture_peer import PeerBinding, run_peer
from t02_capture_pipe_owner import CapturePipeHandles, CapturePipeOwner
from t02_capture_private_channel import CaptureHostFrames, CapturePrivateChannel
from t02_capture_supervisor import CaptureSupervisor, Command
from t02_capture_windows_pipe import WindowsCapturePipe
from t02_event_types import Hold, encode
from t02_event_windows import _OwnedWindowsJob


def test_channel_reads_fragmented_receipt_and_sends_out_of_band_stop() -> None:
    wire = Mock()
    body = encode({"seq": 1, "correlation": "a" * 64, "phase": "armed",
                   "listener_attempted": False, "runtime_attempted": False})
    header = struct.pack("<I", len(body))
    wire.read.side_effect = [header[:1], header[1:], body]
    channel = CapturePrivateChannel(wire, "a" * 64, lambda: 0)
    assert channel.arm(20, 30).phase == "armed"
    with pytest.raises(Hold):
        channel.arm(20, 30)
    channel.signal_stop()
    channel.signal_stop()
    wire.signal_stop.assert_called_once_with()
    wire.write.assert_called_once()


def test_timed_out_overlapped_read_never_resumes_but_can_signal_stop() -> None:
    api = Mock()
    operation = Mock()
    operation.event = 44
    api.ReadFile.return_value = (operation, 997)
    api.WaitForSingleObject.return_value = 258
    pipe = WindowsCapturePipe(11, 12, 13, lambda: 10, api=api)
    with pytest.raises(Hold):
        pipe.read(4, 20)
    api.WaitForSingleObject.assert_called_once_with(44, 10)
    operation.cancel.assert_called_once_with()
    operation.GetOverlappedResult.assert_not_called()
    with pytest.raises(Hold):
        pipe.write(b"data", 30)
    api.WriteFile.assert_not_called()
    pipe.signal_stop()
    api.SetEvent.assert_called_once_with(13)


@pytest.mark.parametrize("active_children", [0, 1])
def test_job_witness_moves_exact_handles_and_requires_empty_tree(
    monkeypatch: pytest.MonkeyPatch, active_children: int,
) -> None:
    kernel = Mock()
    kernel.TerminateJobObject.return_value = True
    kernel.WaitForSingleObject.return_value = 0

    def accounting(*args: object) -> bool:
        getattr(args[2], "_obj").active = active_children
        return True

    kernel.QueryInformationJobObject.side_effect = accounting
    monkeypatch.setattr(role_handles, "_kernel", lambda: kernel)
    role = _OwnedWindowsJob(lambda: 5)
    role._job, role._process = 11, 22
    role._attempted = role._assigned = True
    witness = role_handles.CaptureRoleWitness(role, lambda: 5)
    assert role._job is None and role._process is None
    with pytest.raises(Hold):
        role_handles.CaptureRoleWitness(role, lambda: 5)
    witness.signal()
    kernel.TerminateJobObject.assert_called_once_with(11, 1)
    assert witness.confirm_exact_stop(10) is (active_children == 0)
    kernel.WaitForSingleObject.assert_called_once_with(22, 5)
    witness.close()
    witness.close()
    assert kernel.CloseHandle.call_count == 2


def test_private_client_and_host_share_one_exact_sequence() -> None:
    listener, runtime = Mock(), Mock()
    listener.request_start.return_value = True
    runtime.request_start.return_value = True
    listener.confirm_exact_stop.return_value = True
    runtime.confirm_exact_stop.return_value = True
    host = CaptureSupervisor(lambda: 1, 20, 30, listener, runtime)
    protocol = CaptureHostFrames(host, "a" * 64, 20, 30, lambda: 1)
    pending = bytearray()
    pipe = Mock()

    def write(frame: bytes, deadline: int) -> None:
        assert deadline in (20, 30)
        pending.extend(protocol.on_frame(frame))

    def read(count: int, deadline: int) -> bytes:
        assert deadline in (20, 30)
        chunk = bytes(pending[:count])
        del pending[:count]
        return chunk

    pipe.write.side_effect = write
    pipe.read.side_effect = read
    pipe.signal_stop.side_effect = protocol.stop_event
    channel = CapturePrivateChannel(pipe, "a" * 64, lambda: 1)
    assert channel.arm(20, 30).phase == "armed"
    assert channel.request(Command.LISTENER, 20).listener_attempted
    assert channel.request(Command.RUNTIME, 20).runtime_attempted
    channel.signal_stop()
    assert channel.stop_witness(30).phase == "confirmed"
    listener.signal.assert_called_once_with()
    runtime.signal.assert_called_once_with()


def test_os_provisioner_leaves_only_controller_copies_in_the_parent() -> None:
    api = Mock()
    api.CreateNamedPipe.side_effect = [11, 12]
    api.CreateFile.side_effect = [21, 22]
    api.ConnectNamedPipe.return_value.GetOverlappedResult.return_value = (0, 0)
    api.GetCurrentProcess.return_value = -1
    api.DuplicateHandle.side_effect = [41, 42, 43]
    entropy = iter(("a" * 48, "b" * 48))
    owner = CapturePipeOwner(lambda: 1, api=api, make_event=lambda: 31, nonce=entropy.__next__)
    handles = owner.prepare(20)
    assert handles.controller == (11, 22, 31) and handles.supervisor == (41, 42, 43)
    assert "(41, 42, 43)" not in repr(handles)
    for call in api.CreateNamedPipe.call_args_list:
        assert call.args[1:4] == (0x40080001, 8, 1)
    assert [call.args[1] for call in api.DuplicateHandle.call_args_list] == [12, 21, 31]
    assert all(call.args[4] is True for call in api.DuplicateHandle.call_args_list)
    owner.release_supervisor_copies()
    assert {call.args[0] for call in api.CloseHandle.call_args_list} == {12, 21, 41, 42, 43}
    with pytest.raises(Hold):
        owner.prepare(20)
    owner.close()
    assert {call.args[0] for call in api.CloseHandle.call_args_list} == {11, 12, 21, 22, 31, 41, 42, 43}


def test_guarded_bootstrap_uses_only_exact_child_capabilities_and_stops_both_roles() -> None:
    pair = CapturePipeHandles((11, 12, 13), (21, 22, 23))
    binding = PeerBinding.from_owner(pair, "a" * 64, 20, 30)
    listener, runtime = Mock(), Mock()
    listener.request_start.return_value = True
    runtime.request_start.return_value = True
    listener.confirm_exact_stop.return_value = True
    runtime.confirm_exact_stop.return_value = True
    host = CaptureSupervisor(lambda: 1, 20, 30, listener, runtime)
    events = Mock()
    events.stopped.side_effect = [False] * 6 + [True, True]
    frames = []
    for seq, command in enumerate(("arm", "listener", "runtime", "status"), 1):
        extras = {"intake": 20, "cleanup": 30} if seq == 1 else {}
        body = encode({"action": command, "seq": seq, "correlation": "a" * 64} | extras)
        frames.append(struct.pack("<I", len(body)) + body)
    events.receive.side_effect = frames
    factory = Mock(return_value=events)
    assert run_peer(binding, host, factory, lambda: 1).phase == "confirmed"
    factory.assert_called_once_with((21, 22, 23))
    listener.signal.assert_called_once_with()
    runtime.signal.assert_called_once_with()
    assert events.send.call_count == 4


def test_supervisor_waits_for_stop_even_with_no_controller_bytes() -> None:
    api = Mock()
    operation = Mock()
    operation.event = 44
    api.ReadFile.return_value = (operation, 997)
    api.WaitForMultipleObjects.return_value = 1
    pipe = WindowsCapturePipe(11, 12, 13, lambda: 10, api=api, supervisor=True)
    with pytest.raises(Hold):
        pipe.read(4, 20)
    api.WaitForMultipleObjects.assert_called_once_with([44, 13], False, 10)
    operation.cancel.assert_called_once_with()
    assert pipe.stopped()
