"""Composition regressions for exact stage handoff and two-job custody."""

from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import pytest
import t02_capture_host_entry as entry
import t02_capture_owned_jobs as owned_jobs
import t02_capture_transfer as transfer_module
from t02_capture_bootstrap import ENVIRONMENT_KEY, InheritedCapture
from t02_capture_evidence import PREFIX, SCOPE, CaptureEvidence
from t02_capture_handoff import receive_handoff
from t02_capture_packet import CapturePacket
from t02_capture_peer import PeerBinding
from t02_capture_pipe_owner import CapturePipeHandles
from t02_capture_supervisor import CaptureSupervisor, Command, HostStatus
from t02_event_capture import CaptureBinding, CaptureStore
from t02_event_types import Hold, encode
from test_t02_capture_evidence import ACTIVATION, Provider
from test_t02_capture_lifecycle import record


@pytest.mark.parametrize(("exact_stop", "revoke"), [(True, False), (False, False), (True, True)])
def test_exact_child_transfer_orders_jobs_state_and_role_starts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, exact_stop: bool, revoke: bool,
) -> None:
    packet = CapturePacket.parse(encode(record() | {"state": str(tmp_path / "owner.db")}))
    target = packet.approval
    provider = Provider()
    provider.expected_deadline = packet.intake_cutoff_ms
    provider.records["/pulls/15"]["head"] = {"sha": target.head}
    for ref in (1, 2):
        provider.records[f"/issues/comments/{ref}"]["body"] = PREFIX + encode({
            "head": target.head, "digest": target.digest, "scope": SCOPE,
            "not_before": ACTIVATION, "expires": target.cutoff_ms,
        }).decode()
    evidence = CaptureEvidence(provider, lambda: provider.now)
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
        lambda value: value + 10, descriptor.peer.correlation, 50, 100, approval_refs=(1, 2),
    )
    children, wire = prepared.jobs, prepared.wire
    assert children == (31, 32) and prepared.descriptor == descriptor
    with pytest.raises(Hold):
        receive_handoff(descriptor, wire.replace(b"655", b"654", 1) + b"x", lambda: 0,
                        lambda: ACTIVATION, lambda _: True, evidence=evidence)
    wrong_jobs = Mock(return_value=False)
    with pytest.raises(Hold, match="role handoff"):
        receive_handoff(descriptor, wire, lambda: 0, lambda: ACTIVATION, wrong_jobs, evidence=evidence)
    wrong_jobs.assert_called_once_with(children)
    assert provider.calls == 0
    for denial in ("changed-head", "absent", "wrong-actor", "edited", "stale", "late"):
        before_head = provider.records["/pulls/15"].copy()
        lead = provider.records["/issues/comments/2"]
        before_lead = lead.copy()
        if denial == "changed-head":
            provider.records["/pulls/15"]["head"] = {"sha": "f" * 40}
        elif denial == "absent":
            lead.clear()
        elif denial == "wrong-actor":
            lead["user"] = {"id": 123, "type": "Bot"}
        elif denial == "edited":
            lead["updated_at"] = "2023-11-14T22:13:21Z"
        elif denial == "stale":
            lead["body"] = PREFIX + encode({
                "head": target.head, "digest": target.digest, "scope": SCOPE,
                "not_before": ACTIVATION - 100, "expires": ACTIVATION - 1,
            }).decode()
        else:
            provider.calls = 0
            provider.late = True
        with pytest.raises(Hold, match="child authority"):
            receive_handoff(descriptor, wire, lambda: 0, lambda: provider.now, lambda _: True, evidence=evidence,
                            identify=Mock(side_effect=AssertionError("private state read before authority")))
        assert store.status()[0] == "claimed"
        provider.records["/pulls/15"] = before_head
        provider.records["/issues/comments/2"] = before_lead
        provider.now = ACTIVATION
    provider.calls = 0
    provider.late = False
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

    runtime_role = Mock(confirm_exact_stop=Mock(return_value=exact_stop))

    def runtime(accepted: object, handle: int) -> Mock:
        assert handle == 32
        trace.append("runtime-created")
        return runtime_role

    def peer(binding: PeerBinding, host: CaptureSupervisor, clock: object) -> HostStatus:
        assert binding == descriptor.peer
        assert provider.calls == 4
        assert trace == ["jobs-exact", "listener-created", "runtime-created"]
        assert binding.intake_ms == 50
        assert host.command(Command.LISTENER).listener_attempted
        assert provider.calls == 8
        if revoke:
            provider.records["/pulls/15"]["head"] = {"sha": "f" * 40}
            status = host.command(Command.RUNTIME)
            assert status == HostStatus("confirmed", True, True)
            assert provider.calls == 10
            runtime_role.request_start.assert_not_called()
            runtime_role.signal.assert_called_once()
            return status
        assert host.command(Command.RUNTIME) == HostStatus("runtime-started", True, True)
        assert provider.calls == 12
        runtime_role.request_start.assert_called_once_with(50)
        return host.command(Command.STOP)

    monkeypatch.setattr(entry, "run_native_peer", peer)
    outcome = entry.run_transferred_supervisor(
        descriptor.to_environment()[ENVIRONMENT_KEY], lambda: 0, lambda: ACTIVATION,
        lambda _: True, lambda _: True, verify_jobs, listener, runtime, provider=provider,
    )
    assert outcome == HostStatus("confirmed" if exact_stop else "cleanup-unknown", True, True)
    assert store.status()[0] == ("stopped" if exact_stop else "cleanup-unknown")
    with pytest.raises(Hold):
        receive_handoff(descriptor, wire, lambda: 0, lambda: ACTIVATION, verify_jobs, evidence=evidence)
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


@pytest.mark.parametrize(("ticks", "wall_offsets", "bounds", "allowed"), [
    ((1000, 1001, 1001, 1001), (1, 1), (1050, 1100), True),
    ((1000, 1001, 1001, 1001), (0, 1), (1050, 1100), True),
    ((1000, 1007, 1007, 1007), (0, 7), (1050, 1100), True),
    ((1000, 1010, 1010, 1010), (0, 10), (1060, 1110), False),
    ((1000, 1001, 1001, 1001), (0, 1), (1051, 1101), False),
    ((1000, 1001, 1001, 1001), (1, 1), (1050, 1101), False),
    ((1000, 1001, 1001, 1002, 1002, 1003), (0, 1, 2), (1050, 1100), False),
    ((1002, 1001), (1,), (1050, 1100), False),
    ((1000, 1001, 1001, 1001), (4, 5), (1050, 1100), False),
    ((1000, 1001, 1001, 1001), (3, 1), (1050, 1100), False),
    ((1049, 1050), (49,), (1050, 1100), False),
    ((1048, 1049), (50,), (1050, 1100), False),
])
def test_inherited_window_resamples_without_granting_ambiguous_time(
    ticks: tuple[int, ...], wall_offsets: tuple[int, ...], bounds: tuple[int, int], allowed: bool,
) -> None:
    packet = CapturePacket.parse(encode(record()))
    target = packet.approval
    handoff = InheritedCapture(PeerBinding((11, 12, 13), "a" * 64, *bounds), target.head, target.digest)
    tick, offset = iter(ticks), iter(wall_offsets)
    assert handoff.verifies_packet_window(packet, lambda: next(tick), lambda: ACTIVATION + next(offset)) is allowed
    assert (handoff.peer.intake_ms, handoff.peer.cleanup_ms) == bounds
