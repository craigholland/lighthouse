"""Capture-only integration over synthetic authorized request data."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
from pathlib import Path

import pytest
from t02_event_capture import CaptureBinding, CaptureStore, capture_receiver
from t02_event_rpc import SOURCE_PATH
from t02_event_types import Hold, decode, encode
from t02_events_probe import BINDING, CALLBACK, HTTP, SECRET, subscription

BEARER = "T" * 32
CAPTURE = CaptureBinding("a" * 40, BINDING.proof_id, BINDING.principal, BINDING.activation_ms, BINDING.send_until)


def state(path: Path) -> object:
    with closing(sqlite3.connect(path)) as db:
        return db.execute("SELECT disposition,candidate,captured_ms FROM capture WHERE slot=1").fetchone()


def bound_call(store: CaptureStore, *, bearer: str = BEARER, version: str | None = None,
               change: dict[str, object] | None = None) -> dict[str, object]:
    receiver = capture_receiver(CAPTURE, store, BEARER, lambda: BINDING.activation_ms)
    headers = HTTP | {"Authorization": "Bearer " + BEARER}
    for request in (
        {"jsonrpc": "2.0", "method": "initialize", "id": 1, "params": {
            "protocolVersion": "2025-11-25", "clientInfo": {}, "capabilities": {}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "method": "events/list", "id": 2},
    ):
        result = receiver.respond("127.0.0.1", "POST", SOURCE_PATH, headers, encode(request))
        assert result.status == 202 or "result" in decode(result.body)
    request = {"jsonrpc": "2.0", "method": "events/subscribe", "id": 3, "params": subscription() | (change or {})}
    headers["Authorization"] = "Bearer " + bearer
    if version:
        headers["MCP-Protocol-Version"] = version
    reply = receiver.respond("127.0.0.1", "POST", SOURCE_PATH, headers, encode(request))
    if not reply.body:
        return {"status": reply.status}
    decoded = decode(reply.body)
    assert "result" not in decoded and "error" in decoded
    assert CALLBACK.encode() not in reply.body and SECRET.encode() not in reply.body
    return decoded


def test_capture_refuses_subscription_and_never_overwrites_candidate(tmp_path: Path) -> None:
    path = tmp_path / "capture.sqlite"
    store = CaptureStore(path, CAPTURE)
    store.setup_fixture()
    assert "error" in bound_call(store)
    assert state(path) == ("captured", CALLBACK, BINDING.activation_ms)
    assert SECRET.encode() not in path.read_bytes()
    reopened = CaptureStore(path, CAPTURE)
    assert "error" in bound_call(reopened)
    assert state(path) == ("captured", CALLBACK, BINDING.activation_ms)
    different: dict[str, object] = {"delivery": {"mode": "webhook", "url": CALLBACK + "/other", "secret": SECRET}}
    assert "error" in bound_call(reopened, change=different)
    assert state(path) == ("held", CALLBACK, BINDING.activation_ms)
    assert "error" in bound_call(CaptureStore(path, CAPTURE))
    assert state(path) == ("held", CALLBACK, BINDING.activation_ms)


@pytest.mark.parametrize("mode", ["auth", "proof", "version", "url", "secret"])
def test_bad_requests_cannot_capture(tmp_path: Path, mode: str) -> None:
    path = tmp_path / "capture.sqlite"
    store = CaptureStore(path, CAPTURE)
    store.setup_fixture()
    if mode == "auth":
        assert bound_call(store, bearer="Z" * 32) == {"status": 403}
    elif mode == "proof":
        assert "error" in bound_call(store, change={"arguments": {"proof_id": "wrong"}})
    elif mode == "version":
        assert bound_call(store, version="2020-01-01") == {"status": 400}
    else:
        frame = {"mode": "webhook", "url": CALLBACK, "secret": SECRET}
        frame[mode] = "not-a-supported-value"
        assert "error" in bound_call(store, change={"delivery": frame})
    assert state(path) == ("new", None, None)


def test_competing_store_owners_hold_without_replacing_or_rearming(tmp_path: Path) -> None:
    path = tmp_path / "capture.sqlite"
    first = CaptureStore(path, CAPTURE)
    first.setup_fixture()
    second = CaptureStore(path, CAPTURE)
    frame: dict[str, object] = {"delivery": {"mode": "webhook", "url": CALLBACK + "/other", "secret": SECRET}}
    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(bound_call, first)
        b = pool.submit(bound_call, second, change=frame)
        assert "error" in a.result(timeout=4) and "error" in b.result(timeout=4)
    saved = state(path)
    assert saved in (("held", None, None), ("held", CALLBACK, BINDING.activation_ms),
                     ("held", CALLBACK + "/other", BINDING.activation_ms))
    assert "error" in bound_call(CaptureStore(path, CAPTURE))
    assert state(path) == saved


def test_interruption_after_committed_reservation_never_rearms(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "capture.sqlite"
    store = CaptureStore(path, CAPTURE)
    store.setup_fixture()
    edit = store._edit

    @contextmanager
    def disrupted() -> Iterator[sqlite3.Connection]:
        with edit() as db:
            yield db
        raise Hold("simulated lost durable acknowledgement")

    monkeypatch.setattr(store, "_edit", disrupted)
    assert "error" in bound_call(store)
    assert state(path) == ("reserved", None, None)
    assert "error" in bound_call(CaptureStore(path, CAPTURE))
    assert state(path) == ("held", None, None)
