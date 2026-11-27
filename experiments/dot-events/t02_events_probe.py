"""Worker-free private event-probe entry; ordinary paths are synthetic."""

from __future__ import annotations

import argparse
import base64
import itertools
from collections.abc import Sequence
from pathlib import Path
from tempfile import TemporaryDirectory

from t02_event_rpc import PROBE_HOST, SOURCE_PATH, ProbeRpc, RpcResponse
from t02_event_source import EventSource
from t02_event_types import (
    EVENT,
    VERSION,
    Binding,
    Callback,
    Reply,
    Request,
    decode,
    encode,
)

PROBE_AUTHORITY = "synthetic-principal"
CALLBACK = "https://callback.example.test/probe"
SECRET = "whsec_" + base64.b64encode(bytes(range(32))).decode()
BINDING = Binding("synthetic-proof", PROBE_AUTHORITY, "callback.example.test", "/probe", 1_800_000_000_000)
HTTP = {
    "Host": PROBE_HOST, "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json", "MCP-Protocol-Version": VERSION,
}


class SyntheticNetwork:
    """Fake DNS and HTTPS; records requests for evidence, never opens a socket."""

    def __init__(self) -> None:
        self.calls: list[Request] = []
        self.addresses: tuple[str, ...] = ("8.8.8.8",)
        self.verification: Reply | None = None
        self.responses: list[Reply] = []

    def resolve(self, hostname: str, deadline_ms: int) -> tuple[str, ...]:
        return self.addresses

    def post(self, request: Request) -> Reply:
        self.calls.append(request)
        parsed = decode(request.body)
        if parsed.get("type") == "verification":
            return self.verification or Reply(200, encode({"challenge": parsed["challenge"]}))
        return self.responses.pop(0) if self.responses else Reply(202, b"")


class Fixture:
    """The only composition reachable from ordinary CLI paths."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.now = BINDING.activation_ms
        self.authorized = True
        self.network = SyntheticNetwork()
        self.sequence = itertools.count(1)

    def reopen(self) -> EventSource:
        return EventSource(
            self.path, BINDING, Callback(self.network, lambda: self.now), lambda: self.now,
            lambda: f"synthetic-id-{next(self.sequence):08}", lambda: self.authorized,
        )


def call(
    rpc: ProbeRpc, method: str, params: object,
    *, rid: int | None = 1, principal: str | None = PROBE_AUTHORITY,
) -> RpcResponse:
    request: dict[str, object] = {"jsonrpc": "2.0", "method": method, "params": params}
    if rid is not None:
        request["id"] = rid
    return rpc.serve("POST", SOURCE_PATH, HTTP, encode(request), principal)


def initialize(rpc: ProbeRpc) -> bool:
    params = {"protocolVersion": VERSION, "clientInfo": {"name": "fixture", "version": "1"},
              "capabilities": {}}
    reply = call(rpc, "initialize", params)
    return reply.status == 200 and "result" in decode(reply.body) and (
        call(rpc, "notifications/initialized", {}, rid=None).status == 202
    )


def subscription(*, include_secret: bool = True) -> dict[str, object]:
    delivery = {"mode": "webhook", "url": CALLBACK}
    if include_secret:
        delivery["secret"] = SECRET
    return {"name": EVENT, "arguments": {"proof_id": BINDING.proof_id}, "delivery": delivery}


def dry_run() -> int:
    """Confirm one fake verification and two same-ID application requests."""
    with TemporaryDirectory() as scratch:
        fixture = Fixture(Path(scratch) / "event-probe.sqlite")
        source = fixture.reopen()
        source.setup_disposable()
        rpc = ProbeRpc(source)
        if not initialize(rpc) or "result" not in decode(call(rpc, "events/list", {}).body):
            return 1
        if "result" not in decode(call(rpc, "events/subscribe", subscription()).body):
            return 1
        if source.deliver() != "ack":
            return 1
        source.reserve_restart()
        source = fixture.reopen()
        rpc = ProbeRpc(source)
        if not initialize(rpc) or source.deliver(duplicate=True) != "ack":
            return 1
        if "result" not in decode(call(rpc, "events/unsubscribe", subscription(include_secret=False)).body):
            return 1
        if not fixture.reopen().observe_stop() or len(fixture.network.calls) != 3:
            return 1
        if fixture.network.calls[1].body != fixture.network.calls[2].body:
            return 1
    print("Synthetic verification, two same-ID deliveries, durable stop; Dot receipt unverified.")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline, worker-free Lighthouse event probe.")
    options = parser.add_mutually_exclusive_group()
    options.add_argument("--dry-run", action="store_true")
    options.add_argument("--live", action="store_true", help="activation disabled; no live preflight")
    args = parser.parse_args(argv)
    if args.live:
        parser.exit(2, "Held: live event-probe activation is disabled.\n")
    if args.dry_run:
        return dry_run()
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
