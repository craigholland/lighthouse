"""Offline tests for exact contained listener and runtime bindings."""

from pathlib import Path
from unittest.mock import Mock

import pytest
import t02_capture_listener as listener
import t02_capture_local_windows as local_windows
import t02_capture_roles as roles
from t02_capture_bootstrap import ENVIRONMENT_KEY, InheritedCapture
from t02_capture_evidence import CaptureEvidence
from t02_capture_handoff import AcceptedHandoff, store_identity, write_handoff
from t02_capture_local import LocalCaptureObservation
from t02_capture_packet import CapturePacket
from t02_capture_peer import PeerBinding
from t02_capture_pipe_owner import CapturePipeHandles
from t02_event_capture import CaptureBinding, CaptureStore
from t02_event_types import Hold, encode
from test_t02_capture_evidence import ACTIVATION
from test_t02_capture_lifecycle import record


class MemoryPipe:
    def __init__(self) -> None:
        self.incoming = bytearray()
        self.outgoing = bytearray()
        self.stopped = False

    def read(self, count: int, deadline: int) -> bytes:
        assert deadline == 50
        data = bytes(self.incoming[:min(count, 15)])
        del self.incoming[:len(data)]
        return data

    def write(self, data: bytes, deadline: int) -> None:
        assert deadline == 50
        self.outgoing.extend(data)

    def signal_stop(self) -> None:
        self.stopped = True


def _fixture(
    tmp_path: Path, handles: tuple[int, int, int] = (11, 12, 13),
) -> tuple[AcceptedHandoff, InheritedCapture]:
    packet = CapturePacket.parse(encode(record() | {
        "state": str(tmp_path / "owner.db"),
        "loopback_bearer": str(tmp_path / "loopback-bearer"),
        "platform_key": str(tmp_path / "platform-key"),
    }))
    target = packet.approval
    store = CaptureStore(tmp_path / "owner.db", CaptureBinding(
        target.head, packet.proof_id, packet.principal, ACTIVATION, ACTIVATION + 50,
    ), operation_digest=target.digest)
    store.prepare()
    store.claim(lambda: ACTIVATION)
    store.reserve_handoff(lambda: ACTIVATION)
    descriptor = InheritedCapture(PeerBinding(handles, "a" * 64, 50, 100), target.head, target.digest)
    return AcceptedHandoff(packet, store, (31, 32), (1, 2)), descriptor


@pytest.mark.parametrize("mode", ["ok", "tamper", "wrong-pipe", "invalid-approval", "unreleased"])
def test_child_uses_distinct_private_handoff_after_source_approval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str,
) -> None:
    accepted, descriptor = _fixture(tmp_path)
    pipe = MemoryPipe()
    body = listener.make_listener_handoff(descriptor, accepted, lambda: 0, lambda: ACTIVATION, store_identity)
    write_handoff(pipe, body if mode != "tamper" else body.replace(b'"mac":"', b'"mac":"f'), 50)
    pipe.incoming, pipe.outgoing = pipe.outgoing, bytearray()
    open_pipe = Mock(return_value=pipe)
    wait = Mock(return_value=True)
    evidence = Mock(spec=CaptureEvidence)
    evidence.allows.return_value = mode != "invalid-approval"
    receiver = Mock()
    receiver.start.return_value = True
    receiver.confirmed_quiescent.return_value = True
    monkeypatch.setattr(roles, "fixed_capture_listener", Mock(return_value=receiver))

    def private(
        packet: CapturePacket, key: str, clock: object, deadline: int,
    ) -> str:
        assert mode == "ok"
        assert (packet, key, deadline) == (accepted.packet, "loopback_bearer", 50)
        evidence.allows.assert_called_once_with(packet.approval, 1, 2, before_ms=packet.intake_cutoff_ms)
        assert not pipe.outgoing
        return "q" * 32

    monkeypatch.setattr(roles, "_read_capture_secret", private)
    if mode != "ok":
        monkeypatch.setattr(local_windows, "_canonical", Mock(side_effect=AssertionError("opened before approval")))

    def run() -> str:
        release = mode != "unreleased"
        return listener.run_transferred_listener(
            descriptor.to_environment()[ENVIRONMENT_KEY], lambda: 0, lambda: ACTIVATION,
            lambda handle: handle in (11, 12) and mode != "wrong-pipe", lambda handle: handle == 13,
            open_pipe, wait, evidence, released=lambda: release,
        )

    if mode == "ok":
        assert run() == "stopped"
        assert pipe.outgoing.endswith(listener.listener_ready_receipt(descriptor))
        assert b"q" * 32 not in pipe.outgoing
        wait.assert_called_once_with(13, 50)
        receiver.start.assert_called_once_with(50)
        receiver.request_stop.assert_called_once_with(100)
        receiver.confirmed_quiescent.assert_called_once_with(100)
    else:
        with pytest.raises(Hold):
            run()
        receiver.start.assert_not_called()
        wait.assert_not_called()
        if mode in {"wrong-pipe", "unreleased"}:
            open_pipe.assert_not_called()
        if mode != "invalid-approval":
            evidence.allows.assert_not_called()


def test_host_listener_reserves_exact_job_and_receipt_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    accepted, descriptor = _fixture(tmp_path)
    owner, host, witness = Mock(), Mock(), Mock()
    owner.prepare.return_value = CapturePipeHandles((41, 42, 43), (51, 52, 53))
    host.start_bound.return_value = True
    witness.confirm_exact_stop.return_value = True
    pipe = MemoryPipe()
    monkeypatch.setattr(roles, "CapturePipeOwner", Mock(return_value=owner))
    monkeypatch.setattr(roles, "CaptureListenerHost", Mock(return_value=host))
    monkeypatch.setattr(roles, "CaptureRoleWitness", Mock(return_value=witness))
    monkeypatch.setattr(roles, "WindowsCapturePipe", Mock(return_value=pipe))
    monkeypatch.setattr(roles, "_read_capture_secret", Mock(side_effect=AssertionError("host listener read secret")))

    def ready(*_: object) -> bytes:
        binding = host.start_bound.call_args.args[0]
        assert binding.peer.handles == (51, 52, 53)
        assert binding.peer.correlation != descriptor.peer.correlation
        assert host.start_bound.call_args.kwargs == {"preowned_job": 31}
        assert pipe.outgoing
        return listener.listener_ready_receipt(binding)

    monkeypatch.setattr(roles, "read_handoff", ready)
    with pytest.raises(Hold, match="Job binding"):
        roles.hosted_capture_listener(accepted, 32, descriptor, Path("python.exe"), lambda: 0, lambda: ACTIVATION)
    role = roles.hosted_capture_listener(accepted, 31, descriptor, Path("python.exe"), lambda: 0, lambda: ACTIVATION)
    assert role.request_start(50)
    owner.release_supervisor_copies.assert_called_once_with()
    with pytest.raises(Hold, match="role start held"):
        role.request_start(50)
    assert not role.confirm_exact_stop(100)
    role.signal()
    assert pipe.stopped
    assert not role.confirm_exact_stop(99)
    assert role.confirm_exact_stop(100)
    witness.signal.assert_called_once_with()
    witness.confirm_exact_stop.assert_called_once_with(100)
    witness.close.assert_called_once_with()
    owner.close.assert_called_once_with()


def test_host_runtime_consumes_only_approved_files_and_second_job(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    accepted, descriptor = _fixture(tmp_path)
    key = tmp_path / "platform-key"
    bearer = tmp_path / "loopback-bearer"
    key.write_bytes(b"inert-platform-fixture\n")
    bearer.write_bytes(b"q" * 32 + b"\r\n")
    observation = Mock(spec=LocalCaptureObservation)
    monkeypatch.setattr(roles, "matches_local_capture", Mock(return_value=True))
    role, witness = Mock(), Mock()
    role.start.return_value = True
    witness.confirm_exact_stop.return_value = False
    factory = Mock(return_value=role)
    monkeypatch.setattr(roles, "fixed_capture_runtime", factory)
    monkeypatch.setattr(roles, "CaptureRoleWitness", Mock(return_value=witness))
    with pytest.raises(Hold, match="Job binding"):
        roles.hosted_capture_runtime(accepted, 31, descriptor, observation, lambda: 0, lambda: ACTIVATION)
    inactive = roles.hosted_capture_runtime(accepted, 32, descriptor, observation, lambda: 0, lambda: ACTIVATION)
    factory.assert_not_called()
    assert inactive.request_start(50)
    assert factory.call_args.args[2:4] == ("q" * 32, "inert-platform-fixture")
    assert factory.call_args.kwargs == {"preowned_job": 32}
    inactive.signal()
    assert not inactive.confirm_exact_stop(100)
    assert not inactive.confirm_exact_stop(100)
    witness.confirm_exact_stop.assert_called_once_with(100)
    witness.close.assert_called_once_with()
    role.start.assert_called_once_with(50)


@pytest.mark.parametrize("data", [
    b"", b"q" * 129, b"q" * 32 + b"\n\n", b"q" * 32 + b"\n\r\n",
    b"q" * 32 + b"\0", b"q" * 32 + b"\xff",
])
def test_bounded_reader_holds_malformed_bearer(tmp_path: Path, data: bytes) -> None:
    accepted, _ = _fixture(tmp_path)
    (tmp_path / "loopback-bearer").write_bytes(data)
    with pytest.raises(Hold, match="private input held"):
        roles._read_capture_secret(accepted.packet, "loopback_bearer", lambda: 0, 50)
