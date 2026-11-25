"""Absolute deadline behavior with only inert DNS/HTTP and disposable SQLite."""

from __future__ import annotations

import http.client
import io
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from unittest.mock import Mock

import pytest
import t02_event_dns as dns
import t02_event_https as https
import t02_event_production as prod
from t02_event_evidence import PrivatePacket
from t02_event_source import EventSource
from t02_event_types import Hold, Reply, Request
from t02_events_probe import BINDING, subscription
from test_t02_event_assembly import Lab


def test_deadlined_callback_dns_unblocks_owned_role_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    class LookupLab(Lab):
        def observe_source(self, source: EventSource, deadline_ms: int) -> None:
            try:
                super().observe_source(source, deadline_ms)
            except AssertionError:
                raise Hold("synthetic challenge did not complete") from None

        def addresses(self, hostname: str, deadline_ms: int) -> tuple[str, ...]:
            return https.CallbackSockets(hostname, lambda: self.fixture.now).addresses(hostname, deadline_ms)

    lab = LookupLab(tmp_path / "state.sqlite")
    query = Mock()
    query.start.return_value = 997

    def wait(ms: int) -> bool:
        lab.fixture.now += ms
        return bool(query.cancel.called)

    query.wait.side_effect = wait
    monkeypatch.setattr(dns, "_Query", Mock(return_value=query))
    # The ordinary first operation can be a callback challenge. The fake
    # lets its resolver stall until loss of time, then acknowledges cancel.
    assert lab.run() == "held: incomplete source window"
    query.cancel.assert_called_once()
    query.close.assert_called_once()
    query.answers.assert_not_called()
    assert "delivery" not in lab.trace and "verified TLS" not in lab.trace
    assert lab.trace[-4:] == ["source-request", "runtime-request", "source-confirmed", "runtime-confirmed"]
    assert lab.fixture.now < BINDING.deadline
    assert lab.fixture.reopen().observe_stop()


def test_real_stdlib_header_parser_cannot_continue_past_absolute_deadline() -> None:
    now = 1000
    sock = Mock()
    sock.makefile.return_value = io.BytesIO()
    chunks = iter((b"HTTP/1.1 200 OK\r\n", b"X-First: example\r\n", b"X-Third: forbidden\r\n", b"\r\n"))

    def read(buffer: bytearray) -> int:
        nonlocal now
        now += 500
        chunk = next(chunks)
        buffer[:len(chunk)] = chunk
        return len(chunk)

    sock.recv_into.side_effect = read
    conn = http.client.HTTPConnection("callback.example.test", 443)
    conn.sock = sock
    conn.request("POST", "/probe", b"{}")
    try:
        with pytest.raises(Hold, match="deadline"):
            https._bounded(conn, clock=lambda: now, deadline=2000, limit=32)
    finally:
        conn.close()
    assert sock.recv_into.call_count == 2
    assert now == 2000


def test_production_observer_waits_through_real_subscription_contention(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    lab = Lab(tmp_path / "state.sqlite")
    fixture = lab.fixture
    challenge = Event()
    release = Event()
    waiting = Event()
    original = fixture.network.post

    def post(request: Request) -> Reply:
        if not fixture.network.calls:
            challenge.set()
            if not release.wait(3):
                raise Hold("fixture did not release challenge")
        return original(request)

    monkeypatch.setattr(fixture.network, "post", post)
    monkeypatch.setattr(prod, "_clock", lambda: fixture.now)
    receive = fixture.reopen()
    observe = fixture.reopen()
    readiness = observe.subscription_ready

    def observed() -> bool:
        ready = readiness()
        if not ready:
            waiting.set()
        return ready

    monkeypatch.setattr(observe, "subscription_ready", observed)
    effects = prod.ProductionEffects(PrivatePacket.parse(lab.body), tmp_path)
    listener = Mock()
    listener.restart_once.return_value = True
    monkeypatch.setattr(prod, "LoopbackRole", Mock(return_value=listener))
    effects.prepare_loopback("127.0.0.1", 8765, Mock())

    with ThreadPoolExecutor(max_workers=2) as pool:
        subscribe = pool.submit(receive.subscribe, BINDING.principal, subscription())
        try:
            assert challenge.wait(2)
            begin = time.monotonic()
            proof = pool.submit(effects.observe_source, observe, BINDING.send_until)
            assert waiting.wait(2)
            time.sleep(max(0, begin + 0.65 - time.monotonic()))
            assert not proof.done()
        finally:
            release.set()
        subscribe.result(timeout=3)
        proof.result(timeout=3)

    assert len(fixture.network.calls) == 3
    assert fixture.network.calls[1].body == fixture.network.calls[2].body
    listener.restart_once.assert_called_once_with(BINDING.send_until)


def test_unconfirmed_dns_cancellation_quarantines_request_and_denies_new_effects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    query = Mock()
    query.start.return_value = 997
    query.wait.side_effect = (False, False, False, True)
    construct = Mock(return_value=query)
    monkeypatch.setattr(dns, "_Query", construct)
    monkeypatch.setattr(dns, "_quarantined", None)
    with pytest.raises(Hold, match="termination unconfirmed"):
        dns.resolve("callback.example.test", 2000, lambda: 1000)
    query.cancel.assert_called_once()
    query.close.assert_not_called()
    query.answers.assert_not_called()
    with pytest.raises(Hold, match="previous DNS"):
        dns.resolve("callback.example.test", 2000, lambda: 1000)
    construct.assert_called_once()
    query.close.assert_not_called()
    with pytest.raises(Hold, match="previous DNS"):
        dns.resolve("callback.example.test", 2000, lambda: 1000)
    query.close.assert_called_once()


def test_slow_headers_close_transport_and_both_roles_in_assembled_probe(tmp_path: Path) -> None:
    sock = Mock()
    sock.makefile.return_value = io.BytesIO()
    reads = iter((b"HTTP/1.1 200 OK\r\n", b"X-Late: held\r\n", b"\r\n"))

    class HeaderLab(Lab):
        def open_verified_tls(
            self, *, ip: str, port: int, hostname: str, deadline_ms: int,
        ) -> https._PinnedConnection:
            conn = http.client.HTTPConnection(hostname, port)
            conn.sock = sock

            def raw(buffer: bytearray) -> int:
                self.fixture.now = min(deadline_ms, self.fixture.now + 2500)
                item = next(reads)
                buffer[:len(item)] = item
                return len(item)

            sock.recv_into.side_effect = raw
            return https._PinnedConnection(conn, lambda: self.fixture.now)

        def observe_source(self, source: EventSource, deadline_ms: int) -> None:
            try:
                super().observe_source(source, deadline_ms)
            except AssertionError:
                raise Hold("synthetic challenge did not complete") from None

    lab = HeaderLab(tmp_path / "state.sqlite")
    assert lab.run() == "held: incomplete source window"
    assert sock.recv_into.call_count == 2
    sock.close.assert_called_once()
    assert lab.trace[-4:] == ["source-request", "runtime-request", "source-confirmed", "runtime-confirmed"]
    assert not lab.event_bodies and lab.fixture.reopen().observe_stop()


@pytest.mark.parametrize("expired_after_headers", [True, False])
def test_callback_body_has_its_own_remaining_budget_and_no_retry(
    tmp_path: Path, expired_after_headers: bool,
) -> None:
    calls: list[tuple[bytes, float]] = []
    body_completed = False
    sock = Mock()

    class WriteLab(Lab):
        def open_verified_tls(
            self, *, ip: str, port: int, hostname: str, deadline_ms: int,
        ) -> https._PinnedConnection:
            conn = http.client.HTTPConnection(hostname, port)
            conn.sock = sock
            conn.auto_open = 0

            def raw_write(frame: bytes) -> None:
                nonlocal body_completed
                timeout = float(sock.settimeout.call_args.args[0])
                calls.append((frame, timeout))
                if len(calls) == 1:
                    self.fixture.now = deadline_ms + 1 if expired_after_headers else deadline_ms - 500
                elif timeout < 0.9:
                    self.fixture.now += int(timeout * 1000)
                    raise TimeoutError("fake body exceeds its refreshed budget")
                else:
                    self.fixture.now += 900
                    body_completed = True

            sock.sendall.side_effect = raw_write
            return https._PinnedConnection(conn, lambda: self.fixture.now)

        def observe_source(self, source: EventSource, deadline_ms: int) -> None:
            try:
                super().observe_source(source, deadline_ms)
            except AssertionError:
                raise Hold("synthetic challenge did not complete") from None

    lab = WriteLab(tmp_path / "state.sqlite")
    assert lab.run() == "held: incomplete source window"
    assert calls[0][0].startswith(b"POST /probe HTTP/1.1\r\n")
    assert len(calls) == (1 if expired_after_headers else 2)
    if not expired_after_headers:
        frame, timeout = calls[1]
        assert b'"type":"verification"' in frame
        assert timeout == 0.5
    assert not body_completed
    sock.close.assert_called_once()
    assert lab.trace[-4:] == ["source-request", "runtime-request", "source-confirmed", "runtime-confirmed"]
    assert lab.trace.count("DNS") == 1
    assert not lab.event_bodies and lab.fixture.reopen().observe_stop()
