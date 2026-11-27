"""Fixed dormant composition for review; nothing calls it from the public CLI."""

from __future__ import annotations

import os
import secrets
import time
from pathlib import Path

from t02_event_assembly import LoopbackHttp, Resources, run_injected_assembly
from t02_event_evidence import PrivatePacket
from t02_event_gate import RUNTIME, Packet
from t02_event_https import CallbackSockets, GitHubHttps, remaining
from t02_event_loopback import LoopbackRole
from t02_event_source import EventSource
from t02_event_types import Hold
from t02_event_windows import RuntimeRole


def _clock() -> int:
    return time.time_ns() // 1_000_000


class ProductionEffects:
    """One explicit reviewed runtime bundle, never a discovered executable or target."""

    def __init__(self, private: PrivatePacket, directory: Path) -> None:
        if not directory.is_absolute():
            raise Hold("private bundle path must be absolute")
        self._private = private
        self._directory = directory
        self._runtime: RuntimeRole | None = None
        self._listener: LoopbackRole | None = None

    def _fixed_file(self, name: str) -> Path:
        path = self._directory / name
        if path.resolve(strict=True) != path or not path.is_file():
            raise Hold("private file is not the intended local bundle file")
        return path

    def _read_small(self, name: str) -> str:
        with self._fixed_file(name).open("rb") as source:
            data = source.read(259)
        if len(data) > 258:
            raise Hold("private input exceeds bound")
        return data.removesuffix(b"\r\n").removesuffix(b"\n").decode("ascii")

    def private_resources(self, packet: Packet, deadline_ms: int) -> Resources:
        remaining(_clock, deadline_ms)
        if (
            os.name != "nt" or packet != self._private.packet
            or os.environ.get("COMPUTERNAME", "").casefold() != packet.host.casefold()
        ):
            raise Hold("private bundle host mismatch")
        path = self._fixed_file("event-probe.sqlite")
        bearer = self._read_small("loopback-bearer")
        key = self._read_small("platform-key")
        remaining(_clock, deadline_ms)
        self._runtime = RuntimeRole(self._fixed_file("tunnel-client-runtime.exe"), packet, bearer, key, _clock)
        return Resources(path, bearer, packet.private_binding_digest)

    def runtime_digest(self, deadline_ms: int) -> tuple[str, str]:
        if self._runtime is None:
            raise Hold("runtime not bound")
        return RUNTIME, self._runtime.verified_digest(deadline_ms)

    def prepare_loopback(self, host: str, port: int, handler: LoopbackHttp) -> LoopbackRole:
        if self._listener is not None:
            raise Hold("listener already prepared")
        self._listener = LoopbackRole(host, port, handler, _clock)
        return self._listener

    def prepare_windows_runtime(self, candidate: str, packet: Packet) -> RuntimeRole:
        if candidate != RUNTIME or packet != self._private.packet or self._runtime is None:
            raise Hold("runtime binding unavailable")
        return self._runtime

    def observe_source(self, source: EventSource, deadline_ms: int) -> None:
        """One bounded synthetic event and deliberate duplicate after subscription."""
        while not source.subscription_ready():
            time.sleep(min(0.1, remaining(_clock, deadline_ms)))
        remaining(_clock, deadline_ms)
        if source.deliver() != "ack":
            raise Hold("synthetic first delivery not confirmed")
        remaining(_clock, deadline_ms)
        if self._listener is None:
            raise Hold("source listener unavailable")
        source.reserve_restart()
        if not self._listener.restart_once(deadline_ms):
            raise Hold("owned source restart not confirmed")
        remaining(_clock, deadline_ms)
        if source.deliver(duplicate=True) != "ack":
            raise Hold("synthetic duplicate delivery not confirmed")


def dormant_composition(body: bytes, owner_comment: int, lead_comment: int, directory: Path) -> str:
    """Review path only; the CLI hard hold precedes packet and adapter construction."""
    private = PrivatePacket.parse(body)
    evidence = GitHubHttps(_clock)
    sockets = CallbackSockets(private.binding.callback_host, _clock)
    return run_injected_assembly(
        body, owner_comment, lead_comment, github=evidence, sockets=sockets,
        effects=lambda: ProductionEffects(private, directory), clock=_clock,
        random_id=lambda: secrets.token_urlsafe(24), principal_current=lambda: _clock() < private.binding.send_until,
    )
