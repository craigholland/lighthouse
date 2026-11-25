"""Exact capture-only listener and pinned vendor role selection."""

import hmac
import os
import re
import secrets
import stat
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from t02_capture_bootstrap import InheritedCapture
from t02_capture_file_metadata import require_stable_metadata
from t02_capture_handoff import (
    AcceptedHandoff,
    read_handoff,
    store_identity,
    write_handoff,
)
from t02_capture_listener import listener_ready_receipt, make_listener_handoff
from t02_capture_local import LocalCaptureObservation, matches_local_capture
from t02_capture_local_windows import _canonical
from t02_capture_packet import MAX_PACKET_BYTES, CapturePacket
from t02_capture_peer import PeerBinding
from t02_capture_pipe_owner import CapturePipeOwner
from t02_capture_role_handles import CaptureRoleWitness
from t02_capture_windows_host import CaptureListenerHost
from t02_capture_windows_pipe import WindowsCapturePipe
from t02_event_capture import CaptureStore, capture_receiver
from t02_event_loopback import LoopbackRole
from t02_event_types import Hold, decode
from t02_event_windows import RuntimeRole, _OwnedWindowsJob


@dataclass(frozen=True, repr=False)
class _RuntimeBinding:
    tunnel: str
    platform: str
    runtime_binary_digest: str


def fixed_capture_runtime(
    packet: CapturePacket, local: LocalCaptureObservation, bearer: str, key: str,
    clock: Callable[[], int], *, preowned_job: int | None = None,
) -> RuntimeRole:
    """Select only the attested pinned role using creation-time Job assignment."""
    if not matches_local_capture(packet, local):
        raise Hold("capture runtime local identity unavailable")
    record = decode(packet.canonical, MAX_PACKET_BYTES)
    tunnel, org, digest, executable = (record[name] for name in (
        "tunnel", "organization", "runtime_executable_sha256", "runtime_executable",
    ))
    if not all(isinstance(part, str) for part in (tunnel, org, digest, executable)):
        raise Hold("capture runtime identity unavailable")
    assert isinstance(tunnel, str) and isinstance(org, str)
    assert isinstance(digest, str) and isinstance(executable, str)
    options = {} if preowned_job is None else {"preowned_job": preowned_job}
    return RuntimeRole(
        Path(executable), _RuntimeBinding(tunnel, org, digest), bearer, key, clock, atomic_job=True, **options,
    )


def fixed_capture_listener(
    store: CaptureStore, bearer: str, clock: Callable[[], int], *, rpc_clock: Callable[[], int] | None = None,
) -> LoopbackRole:
    """Select the capture receiver, never an outbound callback sender.

    The caller must be the isolated listener helper; this factory does not
    launch a helper or grant listen authority.
    """
    receiver = capture_receiver(store.binding, store, bearer, rpc_clock if rpc_clock is not None else clock)
    return LoopbackRole("127.0.0.1", 8765, receiver, clock)


_SECRET_FILES = {
    "loopback_bearer": ("loopback-bearer", re.compile(r"[A-Za-z0-9_-]{32,128}"), 128),
    "platform_key": ("platform-key", re.compile(r"[A-Za-z0-9_-]{1,256}"), 256),
}


def _read_capture_secret(packet: CapturePacket, field: str, clock: Callable[[], int], deadline: int) -> str:
    """Read one approved fixed file, once, without echoing private I/O failures."""
    record = decode(packet.canonical, MAX_PACKET_BYTES)
    if field not in _SECRET_FILES or clock() >= deadline:
        raise Hold("capture private input held")
    expected, pattern, size = _SECRET_FILES[field]
    raw_path = record[field]
    if not isinstance(raw_path, str):
        raise Hold("capture private input held")
    path = Path(raw_path)
    try:
        if path.name != expected or _canonical(path, directory=False) != raw_path:
            raise Hold("capture private input held")
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= size + 2 or clock() >= deadline:
            raise Hold("capture private input held")
        with path.open("rb") as stream:
            opened = os.fstat(stream.fileno())
            require_stable_metadata(before, opened, "capture private input held at open", path_to_descriptor=True)
            data = stream.read(size + 3)
            require_stable_metadata(opened, os.fstat(stream.fileno()), "capture private input held after read")
        require_stable_metadata(before, path.lstat(), "capture private input held at path recheck")
        if (len(data) != before.st_size
            or _canonical(path, directory=False) != raw_path or clock() >= deadline):
            raise Hold("capture private input held")
        content = data[:-2] if data.endswith(b"\r\n") else data.removesuffix(b"\n")
        value = content.decode("ascii")
        if pattern.fullmatch(value) is None:
            raise Hold("capture private input held")
        return value
    except (OSError, UnicodeError):
        raise Hold("capture private input held") from None


class _HostedCaptureRole:
    """One exact start and observed owned-tree stop; no retry or replacement."""

    def __init__(self, descriptor: InheritedCapture, mono: Callable[[], int]) -> None:
        self._descriptor = descriptor
        self._mono = mono
        self._attempted = False
        self._signaled = False
        self._signal_failed = False
        self._terminal: bool | None = None
        self._role: _OwnedWindowsJob | None = None
        self._witness: CaptureRoleWitness | None = None
        self._owner: CapturePipeOwner | None = None
        self._pipe: WindowsCapturePipe | None = None

    def _begin(self, deadline: int) -> None:
        if self._attempted or self._signaled or deadline != self._descriptor.peer.intake_ms or self._mono() >= deadline:
            raise Hold("capture fixed role start held")
        self._attempted = True

    def _remember(self, role: _OwnedWindowsJob) -> None:
        self._role = role

    def _observe_spawn(self) -> None:
        if self._role is None:
            raise Hold("capture role root unknown")
        self._witness = CaptureRoleWitness(self._role, self._mono)

    def signal(self) -> None:
        """Signal the one owned role without waiting for its confirmation."""
        if self._signaled:
            return
        self._signaled = True
        try:
            if self._pipe is not None:
                self._pipe.signal_stop()
        except Hold:
            self._signal_failed = True
        finally:
            try:
                if self._witness is not None:
                    self._witness.signal()
                elif self._role is not None:
                    self._role.request_stop(self._descriptor.peer.cleanup_ms)
            except (Hold, OSError):
                self._signal_failed = True
        if self._signal_failed:
            raise Hold("capture role signal held")

    def confirm_exact_stop(self, deadline_ms: int) -> bool:
        """Require the original deadline and never upgrade an unknown observation."""
        if not self._signaled or deadline_ms != self._descriptor.peer.cleanup_ms:
            return False
        if self._terminal is not None:
            return self._terminal
        self._terminal = False
        try:
            if self._witness is not None:
                stopped = self._witness.confirm_exact_stop(deadline_ms)
            elif self._role is not None:
                stopped = self._role.confirmed_quiescent(deadline_ms)
            else:
                stopped = True  # No process or role launch was attempted.
            self._terminal = stopped and not self._signal_failed and self._mono() < deadline_ms
            return self._terminal
        except (Hold, OSError):
            return False
        finally:
            try:
                if self._witness is not None:
                    self._witness.close()
            finally:
                if self._owner is not None:
                    self._owner.close()


class _HostedListener(_HostedCaptureRole):
    def __init__(
        self, accepted: AcceptedHandoff, job: int, descriptor: InheritedCapture, python: Path,
        mono: Callable[[], int], wall: Callable[[], int],
    ) -> None:
        super().__init__(descriptor, mono)
        self._accepted, self._job, self._python, self._wall = accepted, job, python, wall

    def request_start(self, deadline: int) -> bool:
        self._begin(deadline)
        packet = self._accepted.packet
        if not self._descriptor.verifies_packet_window(packet, self._mono, self._wall):
            return False
        self._owner = CapturePipeOwner(self._mono)
        handles = self._owner.prepare(deadline)
        if set((*handles.controller, *handles.supervisor)).intersection(
            (*self._descriptor.peer.handles, *self._accepted.jobs)
        ):
            raise Hold("capture listener channel is not separate")
        descriptor = InheritedCapture(
            PeerBinding.from_owner(handles, secrets.token_hex(32), deadline, self._descriptor.peer.cleanup_ms),
            packet.approval.head, packet.approval.digest,
        )
        self._pipe = WindowsCapturePipe(*handles.controller, self._mono)
        body = make_listener_handoff(descriptor, self._accepted, self._mono, self._wall, store_identity)
        role = CaptureListenerHost(self._python, self._mono)
        self._remember(role)
        try:
            started = role.start_bound(descriptor, deadline, preowned_job=self._job)
            if started:
                self._observe_spawn()
        finally:
            self._owner.release_supervisor_copies()
        if not started or not descriptor.verifies_packet_window(packet, self._mono, self._wall):
            return False
        write_handoff(self._pipe, body, deadline)
        reply = read_handoff(self._pipe, deadline, self._mono)
        return (
            hmac.compare_digest(reply, listener_ready_receipt(descriptor))
            and descriptor.verifies_packet_window(packet, self._mono, self._wall)
        )


class _HostedRuntime(_HostedCaptureRole):
    def __init__(
        self, accepted: AcceptedHandoff, job: int, descriptor: InheritedCapture,
        local: LocalCaptureObservation, mono: Callable[[], int], wall: Callable[[], int],
    ) -> None:
        super().__init__(descriptor, mono)
        self._accepted, self._job, self._local, self._wall = accepted, job, local, wall

    def request_start(self, deadline: int) -> bool:
        self._begin(deadline)
        packet = self._accepted.packet
        if (
            not self._descriptor.verifies_packet_window(packet, self._mono, self._wall)
            or not matches_local_capture(packet, self._local)
            or self._accepted.store.status()[0] != "claimed"
        ):
            return False
        bearer = _read_capture_secret(packet, "loopback_bearer", self._mono, deadline)
        key = _read_capture_secret(packet, "platform_key", self._mono, deadline)
        if not self._descriptor.verifies_packet_window(packet, self._mono, self._wall):
            return False
        role = fixed_capture_runtime(packet, self._local, bearer, key, self._mono, preowned_job=self._job)
        self._remember(role)
        started = role.start(deadline)
        if started:
            self._observe_spawn()
        return started and self._descriptor.verifies_packet_window(packet, self._mono, self._wall)


def hosted_capture_listener(
    accepted: AcceptedHandoff, job: int, descriptor: InheritedCapture, python: Path,
    mono: Callable[[], int], wall: Callable[[], int],
) -> _HostedListener:
    """Construct a dormant fixed listener-role binding for the admitted first Job."""
    if type(job) is not int or job <= 0 or job != accepted.jobs[0]:
        raise Hold("capture listener Job binding held")
    return _HostedListener(accepted, job, descriptor, python, mono, wall)


def hosted_capture_runtime(
    accepted: AcceptedHandoff, job: int, descriptor: InheritedCapture,
    local: LocalCaptureObservation, mono: Callable[[], int], wall: Callable[[], int],
) -> _HostedRuntime:
    """Construct a dormant pinned-runtime binding for the admitted second Job."""
    if type(job) is not int or job <= 0 or job != accepted.jobs[1]:
        raise Hold("capture runtime Job binding held")
    return _HostedRuntime(accepted, job, descriptor, local, mono, wall)
