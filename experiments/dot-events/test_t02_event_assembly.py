"""End-to-end fake-only checks of the fenced event-probe composition."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import astuple
from pathlib import Path

import pytest
from t02_event_assembly import LoopbackHttp, Resources, run_injected_assembly
from t02_event_evidence import API_ROOT, PREFIX, PrivatePacket, ProviderReply
from t02_event_gate import LEAD, LEAD_APP, OWNER, RUNTIME, SCOPE, Packet
from t02_event_rpc import SOURCE_PATH
from t02_event_source import EventSource
from t02_event_types import EVENT, Reply, decode, encode
from t02_events_probe import BINDING, HTTP, Fixture, subscription

BEARER = "synthetic-bearer-" + "x" * 32


class Owned:
    """Fake one controlled process handle; an attempted start always requires cleanup."""

    def __init__(self, lab: Lab, role: str) -> None:
        self.lab = lab
        self.role = role

    def start(self, deadline_ms: int) -> bool:
        self.lab.trace.append(self.role + "-start")
        assert deadline_ms == BINDING.send_until
        return self.role != "runtime" or not self.lab.ambiguous_start

    def request_stop(self, deadline_ms: int) -> None:
        self.lab.trace.append(self.role + "-request")
        assert deadline_ms == BINDING.deadline

    def confirmed_quiescent(self, deadline_ms: int) -> bool:
        self.lab.trace.append(self.role + "-confirmed")
        assert deadline_ms == BINDING.deadline
        return self.role != "runtime" or self.lab.clean


class Tls:
    def __init__(self, lab: Lab) -> None:
        self.lab = lab

    def post(
        self, target: str, headers: Mapping[str, str], body: bytes, *, limit: int, deadline_ms: int,
    ) -> Reply:
        assert target == "/probe" and limit == 1024 and deadline_ms <= BINDING.send_until
        obj = decode(body)
        if obj.get("type") == "verification":
            self.lab.trace.append("challenge")
            return Reply(200, encode({"challenge": obj["challenge"]}))
        self.lab.trace.append("delivery")
        assert obj["name"] == EVENT and obj["eventId"] == headers["webhook-id"]
        self.lab.event_bodies.append(body)
        return Reply(202, b"")

    def close(self) -> None:
        self.lab.trace.append("TLS-close")


class Lab:
    """All role, transport and provider effects are tracked in memory."""

    def __init__(self, path: Path) -> None:
        self.fixture = Fixture(path)
        self.fixture.reopen().setup_disposable()
        self.head = "a" * 40
        self.packet = Packet(
            self.head, "workspace", "dot", "org", "tunnel",
            hashlib.sha256(encode(astuple(BINDING))).hexdigest(),
            "c" * 64, "host", BINDING.activation_ms,
        )
        self.body = encode({"packet": self.packet.__dict__, "binding": BINDING.__dict__})
        self.trace: list[str] = []
        self.event_bodies: list[bytes] = []
        self.handler: LoopbackHttp | None = None
        self.mutation = ""
        self.clean = True
        self.ambiguous_start = False

    def read(self, path: str, *, deadline_ms: int, limit: int) -> ProviderReply:
        assert path.startswith(API_ROOT + "/") and deadline_ms <= BINDING.send_until and limit == 32768
        tail = path.removeprefix(API_ROOT)
        if tail == "/issues/5":
            return ProviderReply(200, encode({
                "number": 5, "state": "open", "labels": [{"name": "lighthouse:blocked"}] if self.mutation == "blocked" else [],
            }))
        if tail == "/pulls/15":
            return ProviderReply(200, encode({
                "number": 15, "state": "open", "draft": True, "merged": False,
                "head": {"sha": "d" * 40 if self.mutation == "head" else self.head}, "base": {"ref": "development"},
            }))
        owner = tail == "/issues/comments/101"
        assert owner or tail == "/issues/comments/102"
        mark = "2026-11-25T00:00:00Z"
        return ProviderReply(200, encode({
            "id": 101 if owner else 102, "issue_url": "https://api.github.com" + API_ROOT + "/issues/5",
            "user": {"id": OWNER if owner else LEAD, "type": "User" if owner else "Bot"},
            "performed_via_github_app": None if owner or self.mutation == "app" else {"id": LEAD_APP},
            "created_at": mark, "updated_at": "newer" if self.mutation == "edited" else mark,
            "body": PREFIX + encode({
                "head": self.head, "digest": self.packet.digest, "scope": SCOPE,
                "not_before": BINDING.activation_ms, "expires": BINDING.deadline,
            }).decode(),
        }))

    def effects(self) -> Lab:
        self.trace.append("factory")
        return self

    def private_resources(self, packet: Packet, deadline_ms: int) -> Resources:
        self.trace.append("private-binding")
        return Resources(self.fixture.path, BEARER, packet.private_binding_digest)

    def runtime_digest(self, deadline_ms: int) -> tuple[str, str]:
        self.trace.append("binary-check")
        return RUNTIME, self.packet.runtime_binary_digest

    def prepare_loopback(self, host: str, port: int, handler: LoopbackHttp) -> Owned:
        assert (host, port) == ("127.0.0.1", 8765)
        self.trace.append("prepare-listener")
        self.handler = handler
        return Owned(self, "source")

    def prepare_windows_runtime(self, candidate: str, packet: Packet) -> Owned:
        assert candidate == RUNTIME and packet == self.packet
        self.trace.append("prepare-owned-runtime")
        return Owned(self, "runtime")

    def addresses(self, hostname: str, deadline_ms: int) -> tuple[str, ...]:
        assert hostname == BINDING.callback_host
        self.trace.append("DNS")
        return ("8.8.8.8",)

    def open_verified_tls(self, *, ip: str, port: int, hostname: str, deadline_ms: int) -> Tls:
        assert (ip, port, hostname) == ("8.8.8.8", 443, BINDING.callback_host)
        self.trace.append("verified TLS")
        return Tls(self)

    def observe_source(self, source: EventSource, deadline_ms: int) -> None:
        self.trace.append("observe")
        handler = self.handler
        assert handler is not None
        req = {"jsonrpc": "2.0", "method": "initialize", "id": 1,
               "params": {"protocolVersion": "2025-11-25", "clientInfo": {}, "capabilities": {}}}
        headers = HTTP | {"Authorization": "Bearer " + BEARER}
        for peer, h in (("127.0.0.1", HTTP), ("8.8.8.8", headers),
                        ("127.0.0.1", headers | {"authorization": "another"})):
            assert handler.respond(peer, "POST", SOURCE_PATH, h, encode(req)).status == 403
        assert len(self.event_bodies) == 0
        for request in (
            req,
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "events/subscribe", "params": subscription()},
        ):
            result = handler.respond("127.0.0.1", "POST", SOURCE_PATH, headers, encode(request))
            assert result.status == 202 or (result.status == 200 and "result" in decode(result.body))
        assert source.deliver() == "ack"
        assert source.deliver(duplicate=True) == "ack"
        source.unsubscribe(BINDING.principal, subscription(include_secret=False))
        assert source.observe_stop()

    def run(self) -> str:
        return run_injected_assembly(
            self.body, 101, 102, github=self, sockets=self, effects=self.effects,
            clock=lambda: self.fixture.now, random_id=lambda: f"token-{next(self.fixture.sequence):08}",
            principal_current=lambda: True,
        )


def test_real_composition_with_fake_effect_order_and_owned_cleanup(tmp_path: Path) -> None:
    lab = Lab(tmp_path / "state.sqlite")
    assert "Dot receipt unverified" in lab.run()
    assert lab.trace == [
        "factory", "private-binding", "binary-check", "prepare-listener", "source-start",
        "prepare-owned-runtime", "runtime-start", "observe",
        "DNS", "verified TLS", "challenge", "TLS-close",
        "DNS", "verified TLS", "delivery", "TLS-close",
        "DNS", "verified TLS", "delivery", "TLS-close",
        "runtime-request", "runtime-confirmed", "source-request", "source-confirmed",
    ]
    assert len(lab.event_bodies) == 2 and lab.event_bodies[0] == lab.event_bodies[1]


@pytest.mark.parametrize("mutation", ["edited", "app", "head", "blocked"])
def test_invalid_fresh_provider_does_not_construct_effects(tmp_path: Path, mutation: str) -> None:
    lab = Lab(tmp_path / "state.sqlite")
    lab.mutation = mutation
    assert lab.run().startswith("held:")
    assert not lab.trace and not lab.event_bodies


def test_parser_rejects_extra_fields_and_wrong_private_binding(tmp_path: Path) -> None:
    lab = Lab(tmp_path / "state.sqlite")
    assert PrivatePacket.parse(lab.body).packet == lab.packet
    for body in (
        encode({"packet": lab.packet.__dict__ | {"approval": True}, "binding": BINDING.__dict__}),
        encode({"packet": lab.packet.__dict__, "binding": BINDING.__dict__ | {"proof_id": "other-proof-id"}}),
    ):
        lab.body = body
        assert lab.run().startswith("held:")
    assert not lab.trace


def test_cleanup_has_to_observe_failed_or_ambiguous_runtime(tmp_path: Path) -> None:
    lab = Lab(tmp_path / "state.sqlite")
    lab.ambiguous_start = True
    lab.clean = False
    assert "shutdown not confirmed" in lab.run()
    assert "observe" not in lab.trace and not lab.event_bodies
    assert lab.trace[-4:] == ["runtime-request", "runtime-confirmed", "source-request", "source-confirmed"]
