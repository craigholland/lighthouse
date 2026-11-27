"""Fixed ownership selection for the detached Windows capture coordinator."""

from __future__ import annotations

import importlib
import os
import secrets
from collections.abc import Callable
from pathlib import Path
from typing import Protocol, cast

from t02_capture_bootstrap import ENVIRONMENT_KEY, InheritedCapture
from t02_capture_composition import CaptureWindow
from t02_capture_controller import TransferredCaptureRoles
from t02_capture_evidence import CaptureEvidence
from t02_capture_lifecycle import CaptureRoles
from t02_capture_listener import run_transferred_listener
from t02_capture_native_cutoff import FixedWindowsCutoff
from t02_capture_owned_jobs import OwnedCaptureJobs
from t02_capture_packet import CapturePacket
from t02_capture_pipe_owner import CapturePipeOwner
from t02_capture_transfer import PreparedTransfer
from t02_capture_windows_host import CaptureSupervisorHost
from t02_capture_windows_pipe import WindowsCapturePipe
from t02_event_capture import CaptureStore
from t02_event_https import GitHubHttps
from t02_event_types import Hold


class _Duplicate(Protocol):
    def WaitForSingleObject(self, handle: int, timeout_ms: int) -> int: ...
    def GetCurrentProcess(self) -> int: ...
    def DuplicateHandle(self, source: int, handle: int, target: int, access: int,
                        inherit: bool, options: int) -> int: ...


def _duplicate(handle: int, inheritable: bool) -> int:
    api = cast(_Duplicate, importlib.import_module("_winapi"))
    current = api.GetCurrentProcess()
    return api.DuplicateHandle(current, handle, current, 0, inheritable, 2)


class DetachedCoordinator(Protocol):
    """Installed independent owner bootstrap, not caller values or a thread fallback."""

    def owns_pipe(self, handle: int) -> bool: ...
    def owns_stop(self, handle: int) -> bool: ...
    def owns_jobs(self, handles: tuple[int, int]) -> bool: ...
    def owns_coordinator_pipe(self, handle: int) -> bool: ...
    def owns_coordinator_stop(self, handle: int) -> bool: ...
    def owns_listener_pipe(self, handle: int) -> bool: ...
    def owns_listener_stop(self, handle: int) -> bool: ...


class _BoundDeadline(Protocol):
    def arm_bound(self, fixed: FixedWindowsCutoff, transfer: PreparedTransfer) -> None: ...
    def signal(self) -> None: ...
    def confirmed(self, deadline: int) -> bool: ...


class _LocalCoordinatorDeadline:
    """Normal stop observation inside the independently started coordinator."""

    def __init__(self, fixed: FixedWindowsCutoff) -> None:
        self._fixed = fixed
        self._armed = self._signalled = False

    def arm_bound(self, fixed: FixedWindowsCutoff, transfer: PreparedTransfer) -> None:
        if self._armed or fixed is not self._fixed or not fixed.roles.confirm_child_copies(transfer.jobs):
            raise Hold("capture coordinator originals differ")
        self._armed = True

    def signal(self) -> None:
        self._signalled = True

    def confirmed(self, deadline: int) -> bool:
        return (self._armed and self._signalled and self._fixed.host.confirmed_quiescent(deadline)
                and self._fixed.roles.originals_empty(deadline))


class _ExactDeadline:
    """Use the same preallocated supervisor and role objects in both launch and cutoff lanes."""

    def __init__(self, fixed: FixedWindowsCutoff, detached: _BoundDeadline) -> None:
        self._fixed, self._detached = fixed, detached
        self._ready = False

    def arm_exact(self, transfer: PreparedTransfer, jobs: OwnedCaptureJobs, host: CaptureSupervisorHost) -> None:
        if (self._ready or jobs is not self._fixed.roles or host is not self._fixed.host
            or not jobs.confirm_child_copies(transfer.jobs)):
            raise Hold("capture native owner binding held")
        self._detached.arm_bound(self._fixed, transfer)
        self._ready = True

    def start_fixed(self, descriptor: InheritedCapture, jobs: tuple[int, int]) -> bool:
        if not self._ready:
            raise Hold("capture native owner not ready")
        return self._fixed.start_fixed(descriptor, jobs, lambda handle: _duplicate(handle, False))

    def signal(self) -> None:
        self._detached.signal()

    def confirmed(self, deadline_ms: int) -> bool:
        return self._ready and self._detached.confirmed(deadline_ms)

    def close(self) -> None:
        self._fixed.close()


class WindowsCaptureOwnership:
    """Select the fixed Windows components, with no optional uncontained launch route."""

    def __init__(
        self, python: Path, wall: Callable[[], int], mono: Callable[[], int], detached: DetachedCoordinator,
        *, duplicate: Callable[[int, bool], int] | None = None,
    ) -> None:
        self._python, self._wall, self._mono, self._detached = python, wall, mono, detached
        self._duplicate = _duplicate if duplicate is None else duplicate

    def coordinator_objects(self, packet: CapturePacket, store: CaptureStore, window: CaptureWindow,
                            refs: tuple[int, int]) -> tuple[FixedWindowsCutoff, CaptureRoles]:
        if store.status()[0] != "claimed":
            raise Hold("capture needs a committed claim")
        fixed = FixedWindowsCutoff(self._python, self._mono)
        try:
            fixed.allocate_supervisor(window.intake, window.cleanup)
            fixed.roles.allocate(window.intake)
            pipes = CapturePipeOwner(self._mono)
        except (Hold, OSError):
            fixed.close()
            raise
        detached = _LocalCoordinatorDeadline(fixed)
        roles = TransferredCaptureRoles(
            packet, store, window, refs, self._wall, self._mono, pipes, fixed.roles, fixed.host,
            _ExactDeadline(fixed, detached), lambda handle: self._duplicate(handle, True),
            secrets.token_hex(32), lambda deadline: _await_candidate(store, self._mono, deadline),
            preallocated=True,
        )
        return fixed, roles

    def owns_coordinator_pipe(self, handle: int) -> bool:
        return self._detached.owns_coordinator_pipe(handle)

    def owns_coordinator_stop(self, handle: int) -> bool:
        return self._detached.owns_coordinator_stop(handle)

    def owns_pipe(self, handle: int) -> bool:
        return self._detached.owns_pipe(handle)

    def owns_stop(self, handle: int) -> bool:
        return self._detached.owns_stop(handle)

    def owns_jobs(self, handles: tuple[int, int]) -> bool:
        return self._detached.owns_jobs(handles)

    def listener_dispatch(
        self, local: Callable[[CapturePacket, int], bool],
    ) -> int:

        def wait_stop(handle: int, deadline: int) -> bool:
            if not self._detached.owns_listener_stop(handle):
                raise Hold("capture listener stop capability held")
            remaining = deadline - self._mono()
            native = cast(_Duplicate, importlib.import_module("_winapi"))
            return remaining > 0 and native.WaitForSingleObject(handle, remaining) == 0

        try:
            disposition = run_transferred_listener(
                os.environ.get(ENVIRONMENT_KEY, ""), self._mono, self._wall,
                self._detached.owns_listener_pipe, self._detached.owns_listener_stop,
                lambda handles: WindowsCapturePipe(*handles, self._mono), wait_stop,
                CaptureEvidence(GitHubHttps(self._wall), self._wall), released=lambda: True, local=local,
            )
            return 0 if disposition == "stopped" else 2
        except (Hold, OSError, ValueError, KeyboardInterrupt):
            return 2


def _await_candidate(store: CaptureStore, mono: Callable[[], int], deadline: int) -> None:
    from time import sleep

    while (remaining := deadline - mono()) > 0:
        if store.status() != ("claimed", "new"):
            return
        sleep(min(0.05, remaining / 1000))
