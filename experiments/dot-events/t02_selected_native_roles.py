"""Harmless native role stand-ins selected only by the offline capture fixture."""

from __future__ import annotations

import ctypes as c
import os
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from t02_capture_handoff import AcceptedHandoff
    from t02_event_capture import CaptureStore

# A standalone isolated role child imports only checked-in sibling modules.
if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from t02_capture_bootstrap import ENVIRONMENT_KEY, InheritedCapture
from t02_capture_listener import run_transferred_listener
from t02_capture_local import LocalCaptureObservation
from t02_capture_packet import MAX_PACKET_BYTES
from t02_capture_roles import _HostedCaptureRole, _HostedListener, _HostedRuntime
from t02_capture_windows_host import CaptureListenerHost
from t02_capture_windows_pipe import WindowsCapturePipe
from t02_event_types import Hold, decode, encode
from t02_event_windows import RuntimeRole, _Accounting, _OwnedWindowsJob
from t02_selected_native_context import FIXTURE_LEDGER, FixtureContext

ROLE_SCRIPT = Path(__file__).resolve()
LISTENER_READY = "listener-ready.json"
RUNTIME_READY = "runtime-ready.json"
RPC_CAPTURED = "rpc-captured.json"
_BEARER = "Q" * 32


def _marker(root: Path, name: str, digest: str) -> None:
    path = root / name
    pending = path.with_suffix(".pending")
    with pending.open("x", encoding="ascii") as stream:
        stream.write(digest)
    pending.rename(path)


def _marked(root: Path, name: str, digest: str) -> bool:
    try:
        with (root / name).open("rb") as stream:
            return stream.read(65) == digest.encode("ascii")
    except FileNotFoundError:
        return False


class _ObservedRole(_HostedCaptureRole):
    """Fixture observation of the exact native witness retained by the real role."""

    def observes_live(self) -> bool:
        witness = self._witness
        if witness is None:
            return False
        kernel = witness._kernel
        accounting = _Accounting()
        return bool(
            kernel.WaitForSingleObject(witness._root, 0) == 258
            and kernel.QueryInformationJobObject(
                witness._job, 1, c.byref(accounting), c.sizeof(accounting), None,
            )
            and accounting.active == 1
        )


class _ListenerHost(CaptureListenerHost):
    """Substitute only the last launcher, preserving exact inherited private endpoints."""

    def __init__(self, context: FixtureContext) -> None:
        super().__init__(context.python.with_name("python.exe"), context.mono)
        self._context = context

    def start_bound(
        self, descriptor: InheritedCapture, deadline_ms: int, *, preowned_job: int | None = None,
    ) -> bool:
        context = self._context
        if deadline_ms != descriptor.peer.intake_ms or preowned_job is None:
            raise Hold("fixture listener bound differs")
        raw = descriptor.to_environment()
        ledger = encode({"role": "listener", "descriptor": raw[ENVIRONMENT_KEY], "jobs": []}).decode("ascii")
        return self._start_owned(
            context.python, ["-I", "-S", str(ROLE_SCRIPT), "listener", str(context.root), context.mode],
            raw | {FIXTURE_LEDGER: ledger}, deadline_ms, bind_at_creation=True,
            inherited=descriptor.peer.handles, preowned_job=preowned_job,
        )


class _ListenerRole(_HostedListener, _ObservedRole):
    def __init__(self, accepted: AcceptedHandoff, job: int, descriptor: InheritedCapture,
                 context: FixtureContext) -> None:
        if job != accepted.jobs[0] or not context.exact(accepted.packet, descriptor.peer.intake_ms):
            raise Hold("fixture listener binding differs")
        super().__init__(accepted, job, descriptor, context.python, context.mono, context.wall)
        self._context = context

    def _new_listener_host(self) -> CaptureListenerHost:
        return _ListenerHost(self._context)


class _RuntimeEffect(RuntimeRole):
    """Replace only the vendor process effect with a bound harmless Python root."""

    def __init__(self, job: int, context: FixtureContext) -> None:
        _OwnedWindowsJob.__init__(self, context.mono)
        self._fixture_job, self._context = job, context

    def start(self, deadline_ms: int) -> bool:
        context = self._context
        if not self._start_owned(
            context.python, ["-I", "-S", str(ROLE_SCRIPT), "runtime", str(context.root), context.mode],
            {}, deadline_ms, bind_at_creation=True, preowned_job=self._fixture_job,
        ):
            return False
        while context.mono() < deadline_ms:
            if _marked(context.root, RUNTIME_READY, context.packet.approval.digest):
                return context.mono() < deadline_ms
            time.sleep(0.005)
        return False


def _local(context: FixtureContext) -> LocalCaptureObservation:
    raw = decode(context.packet.canonical, MAX_PACKET_BYTES)
    def text(field: str) -> str:
        value = raw[field]
        if not isinstance(value, str):
            raise Hold("fixture local projection invalid")
        return value

    return LocalCaptureObservation(
        text("host"), text("repository"), text("checkout"), context.packet.approval.head, True,
        text("runtime_archive_sha256"), text("runtime_executable_sha256"),
        tuple(text(field) for field in ("runtime_archive", "runtime_executable", "platform_key",
                                       "loopback_bearer", "state")),
    )


class _RuntimeRole(_HostedRuntime, _ObservedRole):
    def __init__(self, accepted: AcceptedHandoff, job: int, descriptor: InheritedCapture,
                 context: FixtureContext) -> None:
        if job != accepted.jobs[1] or not context.exact(accepted.packet, descriptor.peer.intake_ms):
            raise Hold("fixture runtime binding differs")
        super().__init__(accepted, job, descriptor, _local(context), context.mono, context.wall)
        self._context = context

    def _read_runtime_input(self, field: str, deadline: int) -> str:
        if self._context.mono() >= deadline or field not in {"loopback_bearer", "platform_key"}:
            raise Hold("fixture runtime input held")
        return _BEARER if field == "loopback_bearer" else "inert-fixture-value"

    def _new_runtime(self, bearer: str, key: str) -> RuntimeRole:
        if (bearer, key) != (_BEARER, "inert-fixture-value"):
            raise Hold("fixture runtime input differs")
        return _RuntimeEffect(self._job, self._context)


FixtureRole = _ListenerRole | _RuntimeRole


def make_listener_role(
    accepted: AcceptedHandoff, job: int, descriptor: InheritedCapture, context: FixtureContext,
) -> FixtureRole:
    return _ListenerRole(accepted, job, descriptor, context)


def make_runtime_role(
    accepted: AcceptedHandoff, job: int, descriptor: InheritedCapture, context: FixtureContext,
) -> FixtureRole:
    return _RuntimeRole(accepted, job, descriptor, context)


def _capture_inert(store: CaptureStore, wall_ms: Callable[[], int]) -> None:
    """Exercise the real receiver using only in-memory synthetic request bytes."""
    from t02_event_capture import capture_receiver
    from t02_event_rpc import SOURCE_PATH
    from t02_event_types import decode, encode
    from t02_events_probe import CALLBACK, HTTP, SECRET, subscription

    receiver = capture_receiver(store.binding, store, _BEARER, wall_ms)
    headers = HTTP | {"Authorization": "Bearer " + _BEARER}
    operations = (
        {"jsonrpc": "2.0", "method": "initialize", "id": 1, "params": {
            "protocolVersion": "2025-11-25", "clientInfo": {}, "capabilities": {}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "method": "events/list", "id": 2},
    )
    for operation in operations:
        reply = receiver.respond("127.0.0.1", "POST", SOURCE_PATH, headers, encode(operation))
        if reply.status != 202 and "result" not in decode(reply.body):
            raise Hold("offline capture handshake held")
    reply = receiver.respond("127.0.0.1", "POST", SOURCE_PATH, headers, encode({
        "jsonrpc": "2.0", "method": "events/subscribe", "id": 3,
        "params": subscription() | {"arguments": {"proof_id": store.binding.proof_id}},
    }))
    result = decode(reply.body)
    if (
        "error" not in result or "result" in result
        or CALLBACK.encode("ascii") in reply.body or SECRET.encode("ascii") in reply.body
        or store.status() != ("claimed", "captured")
    ):
        raise Hold("offline capture candidate held")


class _InertReceiver:
    """Final listener effect only; lifecycle and readiness remain production-owned."""

    def __init__(self, context: FixtureContext, store: CaptureStore, rpc_clock: Callable[[], int]) -> None:
        self._context, self._store, self._rpc_clock = context, store, rpc_clock
        self._active = False

    def start(self, deadline: int) -> bool:
        if self._active or self._context.mono() >= deadline:
            return False
        self._active = True
        return True

    def capture(self) -> None:
        if not self._active:
            raise Hold("fixture receiver was not opened")
        _capture_inert(self._store, self._rpc_clock)
        _marker(self._context.root, RPC_CAPTURED, self._context.packet.approval.digest)

    def request_stop(self, deadline: int) -> None:
        self._active = False

    def confirmed_quiescent(self, deadline: int) -> bool:
        return not self._active and self._context.mono() < deadline


def _listener_main(context: FixtureContext) -> int:
    from t02_selected_native_fixture import trusted

    ledger, raw = trusted("listener")
    descriptor = ledger.descriptor
    if not descriptor.verifies_packet_window(context.packet, context.mono, context.wall):
        return 2
    pipe = WindowsCapturePipe(*descriptor.peer.handles, context.mono)
    effect: _InertReceiver | None = None

    def install(
        store: CaptureStore, bearer: str, clock: Callable[[], int], *, rpc_clock: Callable[[], int],
    ) -> _InertReceiver:
        nonlocal effect
        if effect is not None or bearer != _BEARER or store.path != context.root / "capture.db":
            raise Hold("fixture receiver effects differ")
        effect = _InertReceiver(context, store, rpc_clock)
        return effect

    def bind_pipe(handles: tuple[int, int, int]) -> WindowsCapturePipe:
        if handles != descriptor.peer.handles:
            raise Hold("fixture listener pipe handles differ")
        return pipe

    def wait_stop(handle: int, deadline: int) -> bool:
        if handle != descriptor.peer.handles[2] or effect is None:
            raise Hold("fixture listener stop differs")
        _marker(context.root, LISTENER_READY, context.packet.approval.digest)
        captured = False
        while not pipe.stopped():
            if (not captured and context.mode == "normal" and context.mono() < deadline
                and _marked(context.root, RUNTIME_READY, context.packet.approval.digest)):
                captured = True
                try:
                    effect.capture()
                except (Hold, OSError, ValueError):
                    pass  # Unknown capture cannot end the root or retry.
            time.sleep(0.005)
        return True

    result = run_transferred_listener(
        raw, context.mono, context.wall, ledger.owns_listener_pipe, ledger.owns_listener_stop,
        bind_pipe, wait_stop, context.evidence(), released=lambda: True,
        effect=install, fixture_bearer=lambda: _BEARER,
    )
    return 0 if result == "stopped" else 2


def role_main(role: str, root: Path, mode: str) -> int:
    """Fixed fixture child effects; no socket, provider connection or self-expiry."""
    from t02_capture_composition import open_existing_capture

    if sys.platform != "win32" or not sys.flags.isolated or role not in {"listener", "runtime"}:
        return 2
    try:
        context = FixtureContext.load(root, mode, Path(sys.executable).resolve(strict=True))
        packet = context.packet
        if not packet.approval.activation_ms <= context.wall() < packet.intake_cutoff_ms:
            return 2
        if role == "listener":
            return _listener_main(context)
        if ENVIRONMENT_KEY in os.environ or FIXTURE_LEDGER in os.environ:
            raise Hold("fixture runtime must not inherit the listener channel")
        if open_existing_capture(packet).status() != ("claimed", "new"):
            return 2
        _marker(root, RUNTIME_READY, packet.approval.digest)
    except (Hold, OSError, ValueError):
        return 2
    while True:
        time.sleep(60)


if __name__ == "__main__":
    raise SystemExit(role_main(sys.argv[1], Path(sys.argv[2]), sys.argv[3]) if len(sys.argv) == 4 else 2)
