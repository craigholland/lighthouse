"""Worker-free composition over bounded HTTP, TLS and Windows ownership seams.

These adapters contain the binding and effect ordering, not provider/runtime
activation. No concrete real-effect port is reachable from the ordinary CLI.
"""

from __future__ import annotations

import hashlib
import hmac
import re
from collections.abc import Callable, Mapping
from dataclasses import astuple, dataclass
from pathlib import Path
from typing import Protocol

from t02_event_evidence import GitHubEvidence, PrivatePacket, PublicGitHub
from t02_event_gate import RUNTIME, Packet, ProbeGate
from t02_event_rpc import PROBE_HOST, ProbeRpc, RpcResponse
from t02_event_source import EventSource
from t02_event_types import (
    MAX_BODY,
    Binding,
    Callback,
    Hold,
    Network,
    Reply,
    Request,
    encode,
)


class TlsConnection(Protocol):
    """Verified socket: post must not resolve again or follow a redirect."""

    def post(
        self, target: str, headers: Mapping[str, str], body: bytes,
        *, limit: int, deadline_ms: int,
    ) -> Reply: ...

    def close(self) -> None: ...


class SocketBoundary(Protocol):
    def addresses(self, hostname: str, deadline_ms: int) -> tuple[str, ...]: ...

    def open_verified_tls(
        self, *, ip: str, port: int, hostname: str, deadline_ms: int,
    ) -> TlsConnection: ...


class PinnedTls(Network):
    """Keep DNS, pinned peer, verified SNI, bounded response and timing separate."""

    def __init__(self, socket: SocketBoundary, clock: Callable[[], int]) -> None:
        self.socket = socket
        self.clock = clock

    def resolve(self, hostname: str, deadline_ms: int) -> tuple[str, ...]:
        if self.clock() >= deadline_ms:
            raise Hold("resolution window closed")
        result = self.socket.addresses(hostname, deadline_ms)
        if self.clock() >= deadline_ms:
            raise Hold("resolution window closed")
        return result

    def post(self, request: Request) -> Reply:
        if self.clock() >= request.deadline_ms:
            raise Hold("TLS window closed")
        connection = self.socket.open_verified_tls(
            ip=request.ip, port=443, hostname=request.tls_hostname,
            deadline_ms=request.deadline_ms,
        )
        try:
            if self.clock() >= request.deadline_ms:
                raise Hold("TLS window closed")
            answer = connection.post(
                request.target, request.headers, request.body,
                limit=request.response_limit, deadline_ms=request.deadline_ms,
            )
            if self.clock() >= request.deadline_ms or len(answer.body) > request.response_limit:
                raise Hold("callback deadline or body limit")
            if 300 <= answer.status < 400:
                raise Hold("redirect not permitted")
            return answer
        finally:
            connection.close()


class LoopbackHttp:
    """Authenticate a single proof principal on non-browser loopback requests."""

    def __init__(self, rpc: ProbeRpc, binding: Binding, bearer: str) -> None:
        if not re.fullmatch(r"[a-zA-Z0-9_-]{32,128}", bearer):
            raise Hold("invalid private HTTP binding")
        self._rpc = rpc
        self._binding = binding
        self._expected = ("Bearer " + bearer).encode("ascii")

    def respond(
        self, peer: str, method: str, path: str, headers: Mapping[str, str], body: bytes,
    ) -> RpcResponse:
        normalized = {key.lower(): value for key, value in headers.items()}
        received = normalized.pop("authorization", "")
        if (
            len(normalized) + (1 if received else 0) != len(headers)
            or peer != "127.0.0.1" or len(body) > MAX_BODY
            or normalized.get("host") != PROBE_HOST
            or not received.isascii() or len(received) > 136
            or not hmac.compare_digest(self._expected, received.encode("ascii"))
        ):
            return RpcResponse(403)
        return self._rpc.serve(method, path, normalized, body, self._binding.principal)


class Role(Protocol):
    """Own one effect handle from before its start call through terminal proof."""

    def start(self, deadline_ms: int) -> bool: ...

    def request_stop(self, deadline_ms: int) -> None: ...

    def confirmed_quiescent(self, deadline_ms: int) -> bool: ...


@dataclass(frozen=True)
class Resources:
    """Granted private bindings, loaded only by a future authorized effect port."""

    state_file: Path
    transport_bearer: str
    observed_binding_digest: str


class EffectBoundary(Protocol):
    """A later platform adapter must enforce real Windows containment and TLS."""

    def private_resources(self, packet: Packet, deadline_ms: int) -> Resources: ...

    def runtime_digest(self, deadline_ms: int) -> tuple[str, str]: ...

    def prepare_loopback(self, host: str, port: int, handler: LoopbackHttp) -> Role: ...

    def prepare_windows_runtime(self, candidate: str, packet: Packet) -> Role: ...

    def observe_source(self, source: EventSource, deadline_ms: int) -> None: ...


class BoundLifecycle:
    """Start two fixed roles and stop only handles owned by this invocation."""

    def __init__(
        self, private: PrivatePacket, effects: EffectBoundary, network: Network,
        clock: Callable[[], int], random_id: Callable[[], str], principal_current: Callable[[], bool],
    ) -> None:
        self._private = private
        self._effects = effects
        self._network = network
        self._clock = clock
        self._random_id = random_id
        self._principal_current = principal_current
        self._resources: Resources | None = None
        self._source: EventSource | None = None
        self._local: Role | None = None
        self._runtime: Role | None = None
        self._stop_requested: set[int] = set()

    def verify_private_binding(self, packet: Packet, deadline_ms: int) -> bool:
        if packet != self._private.packet or self._clock() >= deadline_ms:
            return False
        observed = self._effects.private_resources(packet, deadline_ms)
        digest = hashlib.sha256(encode(astuple(self._private.binding))).hexdigest()
        if not (
            self._clock() < deadline_ms and observed.observed_binding_digest == packet.private_binding_digest == digest
            and observed.state_file.is_absolute()
        ):
            return False
        self._resources = observed
        return True

    def verify_pinned_binary(self, packet: Packet, deadline_ms: int) -> bool:
        if self._resources is None or packet != self._private.packet or self._clock() >= deadline_ms:
            return False
        version, digest = self._effects.runtime_digest(deadline_ms)
        return self._clock() < deadline_ms and version == RUNTIME and digest == packet.runtime_binary_digest

    def start_source(self, packet: Packet, deadline_ms: int) -> bool:
        resources = self._resources
        if resources is None or packet != self._private.packet or self._clock() >= deadline_ms or self._local is not None:
            return False
        binding = self._private.binding
        source = EventSource(
            resources.state_file, binding, Callback(self._network, self._clock),
            self._clock, self._random_id, self._principal_current,
        )
        self._source = source
        if source.observe_stop() or self._clock() >= deadline_ms:
            return False
        self._local = self._effects.prepare_loopback(
            "127.0.0.1", 8765, LoopbackHttp(ProbeRpc(source), binding, resources.transport_bearer),
        )
        return self._clock() < deadline_ms and self._local.start(deadline_ms) is True

    def start_runtime(self, packet: Packet, deadline_ms: int) -> bool:
        if self._local is None or packet != self._private.packet or self._clock() >= deadline_ms or self._runtime:
            return False
        self._runtime = self._effects.prepare_windows_runtime(RUNTIME, packet)
        return self._clock() < deadline_ms and self._runtime.start(deadline_ms) is True

    def measure_probe_window(self, deadline_ms: int) -> None:
        if self._source is None or self._runtime is None or self._clock() >= deadline_ms:
            raise Hold("missing admitted roles")
        self._effects.observe_source(self._source, deadline_ms)

    def _request_stop(self, role: Role | None, deadline_ms: int) -> None:
        if role is None or id(role) in self._stop_requested:
            return
        self._stop_requested.add(id(role))
        try:
            role.request_stop(deadline_ms)
        except (OSError, ValueError, TypeError, Hold):
            # The stop result is not the independently observed terminal state.
            pass

    def _stop(self, role: Role | None, deadline_ms: int) -> bool:
        if role is None:
            return True  # No launch attempt can occur before obtaining the role.
        self._request_stop(role, deadline_ms)
        return role.confirmed_quiescent(deadline_ms) is True and self._clock() <= deadline_ms

    def confirm_runtime_stopped(self, deadline_ms: int) -> bool:
        return self._stop(self._runtime, deadline_ms)

    def confirm_source_stopped(self, deadline_ms: int) -> bool:
        # Signal both owned roles before any durability or confirmation wait.
        self._request_stop(self._local, deadline_ms)
        self._request_stop(self._runtime, deadline_ms)
        source = self._source
        if source is None:
            return self._stop(self._local, deadline_ms)
        persisted = self._persist_and_check(source, deadline_ms)
        try:
            quiescent = self._stop(self._local, deadline_ms)
        except (OSError, Hold):
            quiescent = False
        if not persisted and quiescent:
            # Retry only the idempotent local stop after the listener can no
            # longer contend for the state. Never retry delivery or startup.
            persisted = self._persist_and_check(source, deadline_ms)
        return persisted and quiescent

    def _persist_and_check(self, source: EventSource, deadline_ms: int) -> bool:
        if self._clock() >= deadline_ms:
            return False
        try:
            source.stop_for_cleanup(min(0.5, max(0, deadline_ms - self._clock()) / 1000))
        except (OSError, Hold):
            # An uncertain write could have committed. Prove, do not infer.
            pass
        if self._clock() >= deadline_ms:
            return False
        try:
            remaining = min(0.5, max(0, deadline_ms - self._clock()) / 1000)
            return source.durable_stop_confirmed(remaining) and self._clock() <= deadline_ms
        except (OSError, Hold):
            return False


def run_injected_assembly(
    body: bytes, owner_comment: int, lead_comment: int, *,
    github: PublicGitHub, sockets: SocketBoundary, effects: Callable[[], EffectBoundary],
    clock: Callable[[], int], random_id: Callable[[], str], principal_current: Callable[[], bool],
) -> str:
    """Compose all candidate boundaries offline without a live CLI adapter selector."""
    try:
        private = PrivatePacket.parse(body)
        evidence = GitHubEvidence(github, private, clock, owner_comment, lead_comment)
    except (Hold, ValueError, TypeError):
        return "held: private packet invalid"
    return ProbeGate(evidence, clock).run(private.packet, lambda: BoundLifecycle(
        private, effects(), PinnedTls(sockets, clock), clock, random_id, principal_current,
    ))
