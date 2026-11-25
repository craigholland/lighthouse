"""Composition regressions for exact stage handoff and two-job custody."""

from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import pytest
import t02_capture_host_entry as entry
import t02_capture_owned_jobs as owned_jobs
import t02_capture_transfer as transfer_module
from t02_capture_bootstrap import ENVIRONMENT_KEY, InheritedCapture
from t02_capture_handoff import receive_handoff
from t02_capture_packet import CapturePacket
from t02_capture_peer import PeerBinding
from t02_capture_pipe_owner import CapturePipeHandles
from t02_capture_supervisor import CaptureSupervisor, Command, HostStatus
from t02_event_capture import CaptureBinding, CaptureStore
from t02_event_types import Hold, encode
from test_t02_capture_evidence import ACTIVATION
from test_t02_capture_lifecycle import record


@pytest.mark.parametrize("exact_stop", [True, False])
def test_exact_child_transfer_orders_jobs_state_and_role_starts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, exact_stop: bool,
) -> None:
    packet = CapturePacket.parse(encode(record() | {"state": str(tmp_path / "owner.db")}))
    target = packet.approval
    descriptor = InheritedCapture(PeerBinding((11, 12, 13), "a" * 64, 50, 100), target.head, target.digest)
    store = CaptureStore(tmp_path / "owner.db", CaptureBinding(
        target.head, packet.proof_id, packet.principal, ACTIVATION, ACTIVATION + 50,
    ), operation_digest=target.digest)
    store.prepare()
    store.claim(lambda: ACTIVATION)
    kernel = Mock()
    kernel.CreateJobObjectW.side_effect = [21, 22]
    kernel.SetInformationJobObject.return_value = True
    monkeypatch.setattr(owned_jobs, "_kernel", lambda: kernel)
    detached_owner = owned_jobs.OwnedCaptureJobs(lambda: 0)
    pipe_owner = Mock()
    pipe_owner.prepare.return_value = CapturePipeHandles((1, 2, 3), descriptor.peer.handles)
    prepared = transfer_module.prepare_transfer(
        lambda: 0, lambda: ACTIVATION, packet, store, pipe_owner, detached_owner,
        lambda value: value + 10, descriptor.peer.correlation, 50, 100,
    )
    children, wire = prepared.jobs, prepared.wire
    assert children == (31, 32) and prepared.descriptor == descriptor
    with pytest.raises(Hold):
        receive_handoff(descriptor, wire.replace(b"655", b"654", 1) + b"x", lambda: 0,
                        lambda: ACTIVATION, lambda _: True)
    wrong_jobs = Mock(return_value=False)
    with pytest.raises(Hold, match="role handoff"):
        receive_handoff(descriptor, wire, lambda: 0, lambda: ACTIVATION, wrong_jobs)
    wrong_jobs.assert_called_once_with(children)
    pending = bytearray()
    pipe = Mock()
    pipe.write.side_effect = lambda chunk, _: pending.extend(chunk)

    def read(size: int, deadline: int) -> bytes:
        assert deadline == 50
        received = bytes(pending[:min(size, 17)])
        del pending[:len(received)]
        return received

    pipe.read.side_effect = read
    host_launcher = Mock()
    host_launcher.start_transferred.return_value = True
    monkeypatch.setattr(transfer_module, "WindowsCapturePipe", Mock(return_value=pipe))
    assert transfer_module.start_transferred_host(prepared, host_launcher, pipe_owner,
                                                   lambda: 0, detached_owner) is pipe
    host_launcher.start_transferred.assert_called_once_with(descriptor, children)
    pipe_owner.release_supervisor_copies.assert_called_once_with()
    assert {call.args[0] for call in kernel.CloseHandle.call_args_list} == {31, 32}
    monkeypatch.setattr(entry, "WindowsCapturePipe", Mock(return_value=pipe))
    trace: list[str] = []

    def verify_jobs(candidate: tuple[int, int]) -> bool:
        assert candidate == children
        assert kernel.SetInformationJobObject.call_count == 2
        trace.append("jobs-exact")
        return True

    def listener(accepted: object, handle: int) -> Mock:
        assert handle == 31
        with pytest.raises(Hold, match="already consumed"):
            store.reserve_handoff(lambda: ACTIVATION)
        trace.append("listener-created")
        return Mock()

    def runtime(accepted: object, handle: int) -> Mock:
        assert handle == 32
        trace.append("runtime-created")
        return Mock(confirm_exact_stop=Mock(return_value=exact_stop))

    def peer(binding: PeerBinding, host: CaptureSupervisor, clock: object) -> HostStatus:
        assert binding == descriptor.peer
        assert trace == ["jobs-exact", "listener-created", "runtime-created"]
        assert binding.intake_ms == 50
        assert host.command(Command.LISTENER).listener_attempted
        assert host.command(Command.RUNTIME) == HostStatus("runtime-started", True, True)
        return host.command(Command.STOP)

    monkeypatch.setattr(entry, "run_native_peer", peer)
    outcome = entry.run_transferred_supervisor(
        descriptor.to_environment()[ENVIRONMENT_KEY], lambda: 0, lambda: ACTIVATION,
        lambda _: True, lambda _: True, verify_jobs, listener, runtime,
    )
    assert outcome == HostStatus("confirmed" if exact_stop else "cleanup-unknown", True, True)
    assert store.status()[0] == ("stopped" if exact_stop else "cleanup-unknown")
    with pytest.raises(Hold):
        receive_handoff(descriptor, wire, lambda: 0, lambda: ACTIVATION, verify_jobs)
    assert kernel.TerminateJobObject.call_count == 0
    detached_owner.close()


def test_child_deadlines_cannot_extend_packet_window() -> None:
    packet = CapturePacket.parse(encode(record()))
    target = packet.approval
    handoff = InheritedCapture(PeerBinding((11, 12, 13), "a" * 64, 50, 100), target.head, target.digest)
    assert handoff.verifies_packet_window(packet, lambda: 0, lambda: ACTIVATION)
    extended = replace(handoff, peer=replace(handoff.peer, intake_ms=600_000, cleanup_ms=900_000))
    assert not extended.verifies_packet_window(packet, lambda: 0, lambda: ACTIVATION + 49)
    assert not handoff.verifies_packet_window(packet, lambda: 0, lambda: ACTIVATION + 1)
