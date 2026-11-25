"""Exercise packet, exact fake authority, and durable one-use lifecycle."""

import json
from dataclasses import replace
from pathlib import Path

import pytest
from t02_capture_evidence import PREFIX, SCOPE, CaptureEvidence
from t02_capture_lifecycle import guarded_capture
from t02_capture_local import LocalCaptureObservation, matches_local_capture
from t02_capture_packet import CapturePacket
from t02_event_capture import CaptureBinding, CaptureStore, capture_receiver
from t02_event_rpc import SOURCE_PATH
from t02_event_types import EVENT, VERSION, Hold, decode, encode
from t02_events_probe import HTTP, SECRET
from test_t02_capture_evidence import ACTIVATION, Provider


def record() -> dict[str, object]:
    return {
        "version": 1, "scope": SCOPE, "repository": "craigholland/lighthouse",
        "issue": 5, "pull_request": 15, "protocol": VERSION, "host_ip": "127.0.0.1",
        "port": 8765, "source_path": SOURCE_PATH, "event": EVENT,
        "runtime": "tunnel-client-runtime/v0.0.21/windows-amd64", "head": "a" * 40,
        "workspace": "fake-workspace", "dot_profile": "opaque-fixture-profile",
        "organization": "fake-test-organization", "tunnel": "fake-test-tunnel", "host": "fake-test-host",
        "proof_id": "test-capture-proof", "principal": "test-principal", "operation_id": "test-operation",
        "filter": {"proof_id": "test-capture-proof"},
        "checkout": r"C:\synthetic\checkout", "runtime_archive": r"C:\synthetic\runtime.zip",
        "runtime_executable": r"C:\synthetic\runtime.exe", "platform_key": r"C:\synthetic\key.txt",
        "loopback_bearer": r"C:\synthetic\bearer.txt", "state": r"C:\synthetic\store.db",
        "runtime_archive_sha256": "d" * 64, "runtime_executable_sha256": "e" * 64,
        "activation_ms": ACTIVATION, "intake_cutoff_ms": ACTIVATION + 50,
        "cleanup_cutoff_ms": ACTIVATION + 100,
    }


def test_canonical_digest_binds_the_exact_packet() -> None:
    raw = record()
    one = CapturePacket.parse(encode(raw))
    two = CapturePacket.parse(json.dumps(dict(reversed(tuple(raw.items()))), indent=2).encode())
    assert one.approval == two.approval
    assert one.approval.digest != CapturePacket.parse(encode(raw | {"operation_id": "other-operation"})).approval.digest
    assert "synthetic" not in repr(one)


@pytest.mark.parametrize("change", [
    {"callback_url": "not-a-target"}, {"issue": True}, {"checkout": r"C:\synthetic\..\outside"},
    {"state": r"C:\synthetic\key.txt"}, {"intake_cutoff_ms": ACTIVATION + 600_001},
    {"filter": {"proof_id": "wrong"}},
])
def test_packet_rejects_inexact_fields(change: dict[str, object]) -> None:
    with pytest.raises(Hold):
        CapturePacket.parse(encode(record() | change))


class Roles:
    """Synthetic roles; no socket or application process."""

    def __init__(self, store: CaptureStore, mode: str) -> None:
        self.calls: list[str] = []
        self.store, self.mode = store, mode

    def arm(self, cleanup_deadline_ms: int) -> None:
        assert cleanup_deadline_ms == 100
        assert self.store.status() == ("claimed", "new")
        self.calls.append("arm")

    def start_listener(self, intake_deadline_ms: int) -> None:
        assert intake_deadline_ms == 50
        self.calls.append("listener")

    def start_runtime(self, intake_deadline_ms: int) -> None:
        assert intake_deadline_ms == 50
        self.calls.append("runtime")
        if self.mode != "ok":
            raise Hold("synthetic partial startup")

    def wait_candidate(self, intake_deadline_ms: int) -> None:
        assert intake_deadline_ms == 50
        self.calls.append("wait")
        bearer = "T" * 32
        receiver = capture_receiver(self.store.binding, self.store, bearer, lambda: ACTIVATION)
        headers = HTTP | {"Authorization": "Bearer " + bearer}
        for request in (
            {"jsonrpc": "2.0", "method": "initialize", "id": 1, "params": {
                "protocolVersion": VERSION, "clientInfo": {}, "capabilities": {}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
        ):
            reply = receiver.respond("127.0.0.1", "POST", SOURCE_PATH, headers, encode(request))
            assert reply.status == 202 or "result" in decode(reply.body)
        callback = "https://synthetic.example/candidate"
        subscribe = {"jsonrpc": "2.0", "method": "events/subscribe", "id": 2, "params": {
            "name": EVENT, "arguments": {"proof_id": self.store.binding.proof_id},
            "delivery": {"mode": "webhook", "url": callback, "secret": SECRET},
        }}
        reply = receiver.respond("127.0.0.1", "POST", SOURCE_PATH, headers, encode(subscribe))
        assert "error" in decode(reply.body) and "result" not in decode(reply.body)
        assert callback.encode() not in reply.body and SECRET.encode() not in reply.body

    def signal_all(self) -> None:
        self.calls.append("signal")

    def confirmed_stopped(self, cleanup_deadline_ms: int) -> bool:
        assert cleanup_deadline_ms == 100
        self.calls.append("confirm")
        return self.mode != "unknown"


@pytest.mark.parametrize(("mode", "result"), [("ok", "candidate-held"), ("partial", "held"),
                                              ("unknown", "cleanup-unknown")])
def test_guarded_capture_holds_and_never_relaunches(tmp_path: Path, mode: str, result: str) -> None:
    packet = CapturePacket.parse(encode(record()))
    target = packet.approval
    provider = Provider()
    for ref in (1, 2):
        provider.records[f"/issues/comments/{ref}"]["body"] = PREFIX + encode({
            "head": target.head, "digest": target.digest, "scope": SCOPE,
            "not_before": ACTIVATION, "expires": target.cutoff_ms,
        }).decode()
    binding = CaptureBinding(target.head, packet.proof_id, packet.principal, ACTIVATION, ACTIVATION + 50)
    path = tmp_path / "capture.db"
    store = CaptureStore(path, binding, operation_digest=target.digest)
    store.prepare()
    roles = Roles(store, mode)
    evidence = CaptureEvidence(provider, lambda: ACTIVATION)
    local = local_observation(packet)
    assert guarded_capture(packet, store, evidence, 1, 2, lambda: ACTIVATION, lambda: 0,
                           lambda: replace(local, tracked_clean=False), roles) == "denied"
    assert not roles.calls and store.status() == ("prepared", "new")
    assert guarded_capture(packet, store, evidence, 1, 2, lambda: ACTIVATION, lambda: 0,
                           lambda: local, roles) == result
    assert roles.calls == ["arm", "listener", "runtime"] + (["wait"] if mode == "ok" else []) + ["signal", "confirm"]
    reopened = CaptureStore(path, binding, operation_digest=target.digest)
    assert reopened.status()[0] == ("cleanup-unknown" if mode == "unknown" else "stopped")
    with pytest.raises(Hold):
        reopened.capture("https://synthetic.example/other", lambda: ACTIVATION)
    retry = Roles(reopened, mode)
    assert guarded_capture(packet, reopened, evidence, 1, 2, lambda: ACTIVATION, lambda: 0,
                           lambda: local, retry) == "admission-unknown"
    assert not retry.calls


def local_observation(packet: CapturePacket) -> LocalCaptureObservation:
    inputs = record()
    files = tuple(str(inputs[key]) for key in (
        "runtime_archive", "runtime_executable", "platform_key", "loopback_bearer", "state",
    ))
    return LocalCaptureObservation(str(inputs["host"]), str(inputs["repository"]), str(inputs["checkout"]),
                                   packet.approval.head, True, "d" * 64, "e" * 64, files)

def test_local_observation_is_exact_but_does_not_attest_a_real_host() -> None:
    packet = CapturePacket.parse(encode(record()))
    fake = local_observation(packet)
    files = fake.canonical_non_reparse_files
    assert matches_local_capture(packet, fake)
    for drift in (replace(fake, head="b" * 40), replace(fake, tracked_clean=False),
                  replace(fake, archive_sha256="0" * 64), replace(fake, canonical_non_reparse_files=files[:-1]),
                  replace(fake, host="unrelated-host")):
        assert not matches_local_capture(packet, drift)
