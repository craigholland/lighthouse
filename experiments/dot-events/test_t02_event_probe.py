"""Effect-level tests for the worker-free T02 eligibility source."""

from __future__ import annotations

import base64
import hmac
import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from dataclasses import replace
from pathlib import Path

import pytest
from t02_event_gate import (
    LEAD,
    LEAD_APP,
    OWNER,
    REPOSITORY,
    SCOPE,
    Authority,
    Evidence,
    Packet,
    ProbeGate,
)
from t02_event_rpc import SOURCE_PATH, ProbeRpc
from t02_event_source import EventSource
from t02_event_types import EVENT, MARKER, Hold, Reply, decode, encode
from t02_events_probe import (
    BINDING,
    HTTP,
    PROBE_AUTHORITY,
    Fixture,
    call,
    initialize,
    main,
    subscription,
)


@pytest.fixture
def synthetic(tmp_path: Path) -> Fixture:
    fixture = Fixture(tmp_path / "probe.sqlite")
    fixture.reopen().setup_disposable()
    return fixture


def ready(fixture: Fixture) -> ProbeRpc:
    rpc = ProbeRpc(fixture.reopen())
    assert initialize(rpc)
    return rpc


def subscribed(fixture: Fixture) -> ProbeRpc:
    rpc = ready(fixture)
    assert "result" in decode(call(rpc, "events/subscribe", subscription()).body)
    return rpc


def test_documented_lifecycle_and_durable_stop(synthetic: Fixture) -> None:
    rpc = ready(synthetic)
    event = decode(call(rpc, "events/list", {}).body)
    catalog = decode(encode(event["result"]))["events"]
    assert isinstance(catalog, list) and len(catalog) == 1 and catalog[0]["name"] == EVENT
    assert decode(call(rpc, "tools/list", {}).body)["error"]
    first = call(rpc, "events/subscribe", subscription())
    assert call(rpc, "events/subscribe", subscription()) == first
    assert len(synthetic.network.calls) == 1
    assert synthetic.reopen().deliver() == "ack"
    synthetic.now += 1500
    synthetic.reopen().reserve_restart()
    with pytest.raises(Hold):
        synthetic.reopen().reserve_restart()
    assert synthetic.reopen().deliver(duplicate=True) == "ack"
    verify, initial, duplicate = synthetic.network.calls
    assert initial.body == duplicate.body and initial.body != verify.body
    event = decode(initial.body)
    assert event["data"] == {"proof_id": BINDING.proof_id, "marker": MARKER}
    assert event["eventId"] == initial.headers["webhook-id"] == duplicate.headers["webhook-id"]
    assert initial.headers["webhook-timestamp"] != duplicate.headers["webhook-timestamp"]
    new_rpc = ready(synthetic)
    assert "result" in decode(call(new_rpc, "events/unsubscribe", subscription(include_secret=False)).body)
    assert "result" in decode(call(new_rpc, "events/unsubscribe", subscription(include_secret=False)).body)
    assert synthetic.reopen().observe_stop()
    with pytest.raises(Hold):
        synthetic.reopen().deliver(duplicate=True)
    assert len(synthetic.network.calls) == 3
    assert call(new_rpc, "events/subscribe", subscription()).status == 403


@pytest.mark.parametrize("principal", [None, "other-principal", ""])
def test_authentication_required_for_discovery_and_subscription(synthetic: Fixture, principal: str | None) -> None:
    rpc = ready(synthetic)
    assert call(rpc, "events/list", {}, principal=principal).status == 403
    assert call(rpc, "events/subscribe", subscription(), principal=principal).status == 403
    assert synthetic.network.calls == []


def test_strict_protocol_and_malformed_requests(synthetic: Fixture) -> None:
    rpc = ProbeRpc(synthetic.reopen())
    wrong = {"protocolVersion": "2025-03-26", "clientInfo": {}, "capabilities": {}}
    assert "error" in decode(call(rpc, "initialize", wrong).body)
    assert "error" in decode(call(rpc, "events/list", {}).body)
    assert initialize(rpc)
    for body in (b"\xff", b'{"id":1,"id":2}', b"[" * 4097, b'{"params":NaN}'):
        assert "error" in decode(rpc.serve("POST", SOURCE_PATH, HTTP, body, PROBE_AUTHORITY).body)
    assert rpc.serve("GET", SOURCE_PATH, HTTP, b"", PROBE_AUTHORITY).status == 405
    assert rpc.serve("POST", SOURCE_PATH, HTTP | {"Origin": "https://other.test"},
                     b"{}", PROBE_AUTHORITY).status == 403
    assert rpc.serve("POST", SOURCE_PATH, HTTP | {"MCP-Protocol-Version": "2026-07-28"},
                     encode({"jsonrpc": "2.0", "id": 1, "method": "events/list"}),
                     PROBE_AUTHORITY).status == 400
    assert synthetic.network.calls == []


@pytest.mark.parametrize("mutation", ["filter", "principal", "secret", "url", "cursor", "ttl"])
def test_bad_subscription_cannot_reach_callback(synthetic: Fixture, mutation: str) -> None:
    params = subscription()
    if mutation == "filter":
        params["arguments"] = {"proof_id": "incorrect"}
    elif mutation in ("principal", "cursor"):
        params[mutation] = "unexpected"
    elif mutation == "ttl":
        params["ttlMs"] = True
    else:
        assert isinstance(params["delivery"], dict)
        params["delivery"][mutation] = "https://callback.example.test/probe?different" if mutation == "url" else "whsec_invalid"
    assert "error" in decode(call(ready(synthetic), "events/subscribe", params).body)
    assert synthetic.network.calls == []


@pytest.mark.parametrize("bad", [Reply(200, b"{}"), Reply(200, b"\xff"), Reply(302, b""), Reply(200, b"x" * 1025)])
def test_bad_verification_has_no_admission_or_second_attempt(synthetic: Fixture, bad: Reply) -> None:
    synthetic.network.verification = bad
    rpc = ready(synthetic)
    assert "error" in decode(call(rpc, "events/subscribe", subscription()).body)
    assert synthetic.reopen().observe_stop()
    assert call(rpc, "events/subscribe", subscription()).status == 403
    assert len(synthetic.network.calls) == 1


def test_exact_hmac_and_pinned_ip_with_dns_change(synthetic: Fixture) -> None:
    subscribed(synthetic)
    assert synthetic.reopen().deliver() == "ack"
    for request in synthetic.network.calls:
        headers = request.headers
        signed = (headers["webhook-id"] + "." + headers["webhook-timestamp"] + ".").encode() + request.body
        expected = "v1," + base64.b64encode(hmac.digest(bytes(range(32)), signed, "sha256")).decode()
        assert headers["webhook-signature"] == expected
        assert request.ip == "8.8.8.8" and request.tls_hostname == "callback.example.test"
        assert request.target == "/probe" and request.response_limit == 1024
    synthetic.network.addresses = ("8.8.8.8", "127.0.0.1")
    with pytest.raises(Hold, match="nonpublic"):
        synthetic.reopen().deliver(duplicate=True)
    assert len(synthetic.network.calls) == 2
    synthetic.network.addresses = ("1.1.1.1",)
    with pytest.raises(Hold):
        synthetic.reopen().deliver(duplicate=True)
    assert len(synthetic.network.calls) == 2


@pytest.mark.parametrize("stop", [410, 413, 403])
def test_permanent_delivery_failure_tombstones(synthetic: Fixture, stop: int) -> None:
    subscribed(synthetic)
    synthetic.network.responses.append(Reply(stop, b""))
    assert synthetic.reopen().deliver() == "stopped"
    with pytest.raises(Hold):
        synthetic.reopen().deliver(duplicate=True)
    assert synthetic.reopen().observe_stop() and len(synthetic.network.calls) == 2


def test_transient_and_duplicate_share_same_event_and_budget(synthetic: Fixture) -> None:
    subscribed(synthetic)
    synthetic.network.responses.extend([Reply(503, b""), Reply(200, b""), Reply(200, b"")])
    assert synthetic.reopen().deliver() == "retry"
    assert synthetic.reopen().deliver(retry=True) == "ack"
    assert synthetic.reopen().deliver(duplicate=True) == "ack"
    with pytest.raises(Hold):
        synthetic.reopen().deliver(duplicate=True)
    assert len(synthetic.network.calls) == 4
    assert len({request.body for request in synthetic.network.calls[1:]}) == 1


def test_ttl_refresh_capped_and_expiry_durable(synthetic: Fixture) -> None:
    rpc = ready(synthetic)
    params = subscription() | {"ttlMs": 1000}
    assert "result" in decode(call(rpc, "events/subscribe", params).body)
    synthetic.now += 500
    result = decode(call(rpc, "events/subscribe", subscription() | {"ttlMs": None}).body)
    assert result["result"] and len(synthetic.network.calls) == 1
    synthetic.now = BINDING.send_until
    with pytest.raises(Hold):
        synthetic.reopen().deliver()
    synthetic.now = BINDING.deadline
    assert synthetic.reopen().observe_stop()
    synthetic.now = BINDING.activation_ms
    assert synthetic.reopen().observe_stop() and len(synthetic.network.calls) == 1


@pytest.mark.parametrize("damage", ["corrupt", "schema", "missing", "copied"])
def test_state_failure_is_not_reseeded(synthetic: Fixture, damage: str) -> None:
    if damage == "corrupt":
        synthetic.path.write_bytes(b"not sqlite")
    elif damage == "schema":
        with closing(sqlite3.connect(synthetic.path)) as db:
            db.execute("PRAGMA user_version=8")
    elif damage == "missing":
        synthetic.path.unlink()
    else:
        copy = synthetic.path.with_name("copy.sqlite")
        copy.write_bytes(synthetic.path.read_bytes())
        synthetic.path = copy
    with pytest.raises(Hold):
        synthetic.reopen().observe_stop()
    assert synthetic.path.exists() == (damage != "missing")
    assert not synthetic.network.calls


def test_lost_durable_delivery_confirmation_cannot_retry(
    synthetic: Fixture, monkeypatch: pytest.MonkeyPatch,
) -> None:
    subscribed(synthetic)
    original = EventSource._edit
    count = 0

    @contextmanager
    def ambiguous(self: EventSource, *, check: bool = True) -> Iterator[sqlite3.Connection]:
        nonlocal count
        with original(self, check=check) as db:
            yield db
        count += 1
        if count == 2:  # Lose the committed delivery-intent result; don't send.
            raise Hold("simulated uncertain persistence")

    with monkeypatch.context() as patch:
        patch.setattr(EventSource, "_edit", ambiguous)
        with pytest.raises(Hold):
            synthetic.reopen().deliver()
    for duplicate in (False, True):
        with pytest.raises(Hold):
            synthetic.reopen().deliver(duplicate=duplicate)
    assert len(synthetic.network.calls) == 1


def sample_packet() -> tuple[Packet, Authority]:
    packet = Packet("a" * 40, "workspace", "dot", "organization", "tunnel",
                    "b" * 64, "c" * 64, "host", BINDING.activation_ms)
    owner = Evidence(REPOSITORY, 5, 15, OWNER, None, SCOPE, packet.head, packet.digest,
                     BINDING.activation_ms, BINDING.deadline)
    return packet, Authority(packet.head, owner, replace(owner, actor=LEAD, app=LEAD_APP))


class EvidencePort:
    def __init__(self, authority: Authority | None) -> None:
        self.authority = authority

    def current(self) -> Authority | None:
        return self.authority


class LifecyclePort:
    """Records fixed-role effects instead of running anything."""

    def __init__(self, fixture: Fixture) -> None:
        self.fixture = fixture
        self.calls: list[str] = []
        self.shutdown = True
        self.start_ok = True

    def verify_private_binding(self, packet: Packet, deadline_ms: int) -> bool:
        self.calls.append("private-binding")
        return True

    def verify_pinned_binary(self, packet: Packet, deadline_ms: int) -> bool:
        self.calls.append("pinned-binary")
        assert deadline_ms == BINDING.send_until
        return True

    def start_source(self, packet: Packet, deadline_ms: int) -> bool:
        self.calls.append("source")
        assert deadline_ms == BINDING.send_until
        return True

    def start_runtime(self, packet: Packet, deadline_ms: int) -> bool:
        self.calls.append("runtime")
        return self.start_ok

    def measure_probe_window(self, deadline_ms: int) -> None:
        self.calls.append("measure")
        self.fixture.now = deadline_ms

    def confirm_runtime_stopped(self, deadline_ms: int) -> bool:
        self.calls.append("confirm runtime")
        assert deadline_ms == BINDING.deadline
        return self.shutdown

    def confirm_source_stopped(self, deadline_ms: int) -> bool:
        self.calls.append("confirm source")
        assert deadline_ms == BINDING.deadline
        return True


@pytest.mark.parametrize("different", ["missing", "head", "owner", "app", "scope", "digest", "expired", "binding"])
def test_no_effect_factory_on_untrusted_authority(synthetic: Fixture, different: str) -> None:
    packet, authority = sample_packet()
    provider = EvidencePort(authority)
    if different == "missing":
        provider.authority = None
    elif different == "head":
        provider.authority = replace(authority, head="d" * 40)
    elif different == "binding":
        packet = replace(packet, workspace="other")
    elif different == "owner":
        provider.authority = replace(authority, owner=replace(authority.owner, actor=LEAD))
    else:
        changes = {"app": {"app": 1}, "scope": {"scope": "other"}, "digest": {"digest": "d" * 64},
                   "expired": {"expires": BINDING.activation_ms}}
        lead = replace(authority.lead, **changes[different])  # type: ignore[arg-type]
        provider.authority = replace(authority, lead=lead)

    def forbidden() -> LifecyclePort:
        pytest.fail("unauthorized gate constructed effect-side factory")

    assert ProbeGate(provider, lambda: synthetic.now).run(packet, forbidden).startswith("held:")


@pytest.mark.parametrize("start_ok, shutdown", [(True, True), (True, False), (False, True)])
def test_fixed_lifecycle_deadlines_and_confirmation(synthetic: Fixture, start_ok: bool, shutdown: bool) -> None:
    packet, authority = sample_packet()
    port = LifecyclePort(synthetic)
    port.start_ok = start_ok
    port.shutdown = shutdown
    result = ProbeGate(EvidencePort(authority), lambda: synthetic.now).run(packet, lambda: port)
    expected = ["private-binding", "pinned-binary", "source", "runtime"]
    if start_ok:
        expected.append("measure")
    assert port.calls == [*expected, "confirm runtime", "confirm source"]
    assert result.startswith("held:") == (not start_ok or not shutdown)


def test_cli_all_ordinary_paths_are_inert(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert main([]) == 0
    with pytest.raises(SystemExit) as help_exit:
        main(["--help"])
    assert help_exit.value.code == 0
    with pytest.raises(SystemExit) as denied:
        main(["--live"])
    assert denied.value.code == 2
    assert main(["--dry-run"]) == 0
    assert list(tmp_path.iterdir()) == []
