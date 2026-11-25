"""Backend verification without real provider, socket, subprocess or credentials."""

from __future__ import annotations

import http.client
import socket
import ssl
from pathlib import Path
from unittest.mock import Mock

import pytest
import t02_event_https as https
import t02_event_loopback as loopback
import t02_event_production as prod
import t02_event_windows as windows
from t02_event_evidence import API_ROOT, ProviderReply
from t02_event_gate import Packet
from t02_event_rpc import RpcResponse
from t02_event_types import Hold
from t02_events_probe import main


def connection(*, status: int = 200, chunks: tuple[bytes, ...] = (b"{}", b"")) -> Mock:
    target = Mock()
    response = Mock(status=status)
    response.read1.side_effect = chunks
    context = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    context.return_value = response
    target.getresponse = context
    return target


def test_public_get_fixed_tls_origin_and_transport_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = connection()
    build = Mock(return_value=conn)
    tls = Mock()
    monkeypatch.setattr(http.client, "HTTPSConnection", build)
    monkeypatch.setattr(ssl, "create_default_context", tls)
    client = https.GitHubHttps(lambda: 1000)
    assert client.read(API_ROOT + "/issues/5", deadline_ms=2000, limit=16) == ProviderReply(200, b"{}")
    build.assert_called_once_with("api.github.com", 443, context=tls.return_value, timeout=1)
    args, kwargs = conn.request.call_args
    assert args == ("GET", API_ROOT + "/issues/5")
    assert {h.lower() for h in kwargs["headers"]} == {"accept", "connection", "user-agent"}
    conn.close.assert_called_once()
    with pytest.raises(Hold):
        client.read(API_ROOT + "/issues/5?other=1", deadline_ms=2000, limit=16)
    assert build.call_count == 1


@pytest.mark.parametrize("status,chunks", [(302, (b"",)), (200, (b"x" * 17,))])
def test_public_get_closes_on_redirect_or_oversize(
    monkeypatch: pytest.MonkeyPatch, status: int, chunks: tuple[bytes, ...],
) -> None:
    conn = connection(status=status, chunks=chunks)
    build = Mock(return_value=conn)
    monkeypatch.setattr(http.client, "HTTPSConnection", build)
    monkeypatch.setattr(ssl, "create_default_context", Mock())
    with pytest.raises(Hold):
        https.GitHubHttps(lambda: 1000).read(API_ROOT + "/pulls/15", deadline_ms=2000, limit=16)
    assert build.call_count == 1
    conn.close.assert_called_once()


def test_callback_connects_numeric_peer_and_verifies_original_sni(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = connection()
    socket_factory = Mock()
    dns = Mock()
    context = Mock()
    monkeypatch.setattr(socket, "socket", socket_factory)
    monkeypatch.setattr(socket, "getaddrinfo", dns)
    monkeypatch.setattr(ssl, "create_default_context", Mock(return_value=context))
    monkeypatch.setattr(http.client, "HTTPConnection", Mock(return_value=conn))
    boundary = https.CallbackSockets("callback.example.test", lambda: 1000)
    with pytest.raises(Hold):
        boundary.open_verified_tls(ip="127.0.0.1", hostname="callback.example.test", port=443, deadline_ms=2000)
    assert not socket_factory.called
    sock = boundary.open_verified_tls(ip="8.8.8.8", hostname="callback.example.test", port=443, deadline_ms=2000)
    assert not dns.called
    socket_factory.return_value.connect.assert_called_once_with(("8.8.8.8", 443))
    context.wrap_socket.assert_called_once_with(socket_factory.return_value, server_hostname="callback.example.test")
    assert sock.post("/probe", {"Content-Type": "application/json"}, b"{}", limit=16, deadline_ms=2000).body == b"{}"
    conn.request.assert_called_once_with(
        "POST", "/probe", b"{}", {"Content-Type": "application/json", "Connection": "close"},
    )
    sock.close()
    conn.close.assert_called_once()


@pytest.mark.parametrize("fields,dispatch", [
    (b"Content-Length: 2\r\nHost: 127.0.0.1:8765", True),
    (b"Content-Length: 2\r\nHost: 127.0.0.1:8765\r\nhost: 127.0.0.1:8765", False),
    (b"Transfer-Encoding: chunked\r\nContent-Length: 2", False),
    (b"Content-Length: 4097", False),
])
def test_loopback_bounded_framing(fields: bytes, dispatch: bool) -> None:
    conn = Mock()
    conn.recv.side_effect = (b"POST /mcp HTTP/1.1\r\n" + fields + b"\r\n\r\n", b"{}")
    handler = Mock()
    handler.respond.return_value = RpcResponse(403)
    loopback.serve_one(conn, "127.0.0.1", handler, lambda: 1000, 2000)
    assert handler.respond.called is dispatch
    if dispatch:
        assert handler.respond.call_args.args[-1] == b"{}"
        assert b"403" in conn.sendall.call_args.args[0]
    else:
        assert not conn.sendall.called


def test_windows_role_never_resumes_unassigned_child_and_requires_empty_job(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "tunnel-client-runtime.exe"
    packet = Packet("a" * 40, "workspace", "dot", "org-test", "tunnel_" + "z" * 32,
                    "b" * 64, "c" * 64, "host", 1000)
    role = windows.RuntimeRole(path, packet, "a" * 32, "inert-key", lambda: 1000)
    monkeypatch.setattr(role, "verified_digest", lambda _: packet.runtime_binary_digest)
    monkeypatch.setenv("SystemRoot", str(tmp_path))
    k = Mock()
    k.CreateJobObjectW.return_value = 11

    def create(*args: object) -> bool:
        proc = getattr(args[-1], "_obj")
        proc.process = 22
        proc.thread = 33
        return True

    k.CreateProcessW.side_effect = create
    k.AssignProcessToJobObject.return_value = False
    k.WaitForSingleObject.side_effect = [258, 0]
    k.QueryInformationJobObject.return_value = True
    monkeypatch.setattr(windows, "_kernel", lambda: k)
    assert not role.start(2000)
    assert not role.start(2000)
    k.ResumeThread.assert_not_called()
    role.request_stop(3000)
    k.TerminateProcess.assert_called_once_with(22, 1)
    assert role.confirmed_quiescent(3000)
    assert k.CloseHandle.call_count == 3


def test_cli_never_constructs_dormant_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    forbid = Mock(side_effect=AssertionError("no live construction"))
    monkeypatch.setattr(prod, "GitHubHttps", forbid)
    monkeypatch.setattr(prod, "ProductionEffects", forbid)
    assert main([]) == 0
    assert main(["--dry-run"]) == 0
    with pytest.raises(SystemExit) as result:
        main(["--live"])
    assert result.value.code == 2
    forbid.assert_not_called()


def test_fixed_composition_rejects_untrusted_provider_without_loading_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from t02_events_probe import BINDING
    from test_t02_event_assembly import Lab

    lab = Lab(tmp_path / "state.sqlite")
    monkeypatch.setattr(prod, "_clock", lambda: BINDING.activation_ms)
    conn = connection(status=403)
    make = Mock(return_value=conn)
    denied = Mock(side_effect=AssertionError("untrusted evidence admitted effects"))
    monkeypatch.setattr(http.client, "HTTPSConnection", make)
    monkeypatch.setattr(ssl, "create_default_context", Mock())
    monkeypatch.setattr(prod, "ProductionEffects", denied)
    assert prod.dormant_composition(lab.body, 101, 102, tmp_path) == "held: exact approval unavailable"
    make.assert_called_once()
    denied.assert_not_called()


def test_production_observation_sequences_restart_between_deliveries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from t02_event_evidence import PrivatePacket
    from t02_events_probe import BINDING
    from test_t02_event_assembly import Lab

    lab = Lab(tmp_path / "state.sqlite")
    trace = Mock()
    source = trace.source
    source.subscription_ready.return_value = True
    source.deliver.return_value = "ack"
    trace.listener.restart_once.return_value = True
    monkeypatch.setattr(prod, "_clock", lambda: BINDING.activation_ms)
    monkeypatch.setattr(prod, "LoopbackRole", Mock(return_value=trace.listener))
    effects = prod.ProductionEffects(PrivatePacket.parse(lab.body), tmp_path)
    effects.prepare_loopback("127.0.0.1", 8765, Mock())
    effects.observe_source(source, BINDING.send_until)
    assert [c[0] for c in trace.mock_calls] == [
        "source.subscription_ready", "source.deliver", "source.reserve_restart",
        "listener.restart_once", "source.deliver",
    ]
    assert source.deliver.call_args.kwargs == {"duplicate": True}
