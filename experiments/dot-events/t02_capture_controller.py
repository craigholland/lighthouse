"""Controller-side binding of the one claimed capture to its fixed helper."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from t02_capture_bootstrap import InheritedCapture
from t02_capture_composition import CaptureWindow
from t02_capture_host_channel import CaptureHostedRoles
from t02_capture_owned_jobs import OwnedCaptureJobs
from t02_capture_packet import CapturePacket
from t02_capture_pipe_owner import CapturePipeOwner
from t02_capture_private_channel import CapturePrivateChannel
from t02_capture_transfer import (
    PreparedTransfer,
    prepare_transfer,
    start_transferred_host,
)
from t02_capture_windows_host import CaptureSupervisorHost
from t02_event_capture import CaptureStore
from t02_event_types import Hold


class IndependentDeadline(Protocol):
    """The external native owner is armed before any supervisor spawn."""

    def arm_exact(self, transfer: PreparedTransfer, jobs: OwnedCaptureJobs, host: CaptureSupervisorHost) -> None: ...
    def start_fixed(self, descriptor: InheritedCapture, jobs: tuple[int, int]) -> bool: ...
    def signal(self) -> None: ...
    def confirmed(self, deadline_ms: int) -> bool: ...
    def close(self) -> None: ...


class TransferredCaptureRoles:
    """Bind the actual transfer/control frame path to one independent owner and one claim."""

    def __init__(
        self, packet: CapturePacket, store: CaptureStore, window: CaptureWindow,
        refs: tuple[int, int], wall: Callable[[], int], mono: Callable[[], int],
        pipes: CapturePipeOwner, jobs: OwnedCaptureJobs, host: CaptureSupervisorHost,
        deadline_owner: IndependentDeadline, duplicate_job: Callable[[int], int], correlation: str,
        wait_candidate: Callable[[int], None], *, preallocated: bool = False,
    ) -> None:
        self._packet, self._store, self._window, self._refs = packet, store, window, refs
        self._wall, self._mono = wall, mono
        self._pipes, self._jobs, self._host = pipes, jobs, host
        self._deadline_owner, self._duplicate_job = deadline_owner, duplicate_job
        self._correlation, self._wait_candidate = correlation, wait_candidate
        self._roles: CaptureHostedRoles | None = None
        self._preallocated = preallocated
        self._attempted = False
        self._owner_armed = False
        self._owner_attempted = False

    def arm(self, cleanup_deadline_ms: int) -> None:
        if self._attempted or self._window.cleanup != cleanup_deadline_ms:
            raise Hold("capture transfer not repeatable")
        self._attempted = True
        transfer = prepare_transfer(
            self._mono, self._wall, self._packet, self._store, self._pipes, self._jobs,
            self._duplicate_job, self._correlation, self._window.intake, self._window.cleanup, approval_refs=self._refs,
            preallocated=self._preallocated,
        )
        self._owner_attempted = True
        self._deadline_owner.arm_exact(transfer, self._jobs, self._host)
        self._owner_armed = True
        if self._mono() >= self._window.intake:
            raise Hold("capture watchdog acknowledgement expired")
        pipe = start_transferred_host(
            transfer, self._host, self._pipes, self._mono, self._jobs, spawn=self._deadline_owner.start_fixed,
        )
        channel = CapturePrivateChannel(pipe, self._correlation, self._mono)
        self._roles = CaptureHostedRoles(
            channel, self._window.intake, self._window.cleanup, self._mono, self._wait_candidate,
        )
        self._roles.arm(cleanup_deadline_ms)

    def _bound(self) -> CaptureHostedRoles:
        if self._roles is None:
            raise Hold("capture roles unavailable")
        return self._roles

    def start_listener(self, intake_deadline_ms: int) -> None:
        self._bound().start_listener(intake_deadline_ms)

    def start_runtime(self, intake_deadline_ms: int) -> None:
        self._bound().start_runtime(intake_deadline_ms)

    def wait_candidate(self, intake_deadline_ms: int) -> None:
        self._bound().wait_candidate(intake_deadline_ms)

    def signal_all(self) -> None:
        try:
            if self._roles is not None:
                self._roles.signal_all()
        finally:
            if self._owner_attempted:
                self._deadline_owner.signal()

    def confirmed_stopped(self, cleanup_deadline_ms: int) -> bool:
        try:
            try:
                receipt = self._roles is not None and self._roles.confirmed_stopped(cleanup_deadline_ms)
            except (Hold, OSError):
                receipt = False
            fallback = self._owner_armed and self._deadline_owner.confirmed(cleanup_deadline_ms)
            return bool(receipt and fallback and self._mono() < cleanup_deadline_ms)
        finally:
            try:
                self._deadline_owner.close()
            finally:
                self._pipes.close()
                self._jobs.close()
