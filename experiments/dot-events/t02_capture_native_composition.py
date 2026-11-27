"""One release boundary for the fixed native capture controller and helpers."""

from __future__ import annotations

import os
import platform
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from t02_capture_bootstrap import ENVIRONMENT_KEY, InheritedCapture
from t02_capture_composition import (
    CaptureWindow,
    open_existing_capture,
)
from t02_capture_coordinator_windows import (
    CaptureCoordinatorHost,
    dispatch_owned,
    owned_entry,
)
from t02_capture_evidence import CaptureEvidence
from t02_capture_handoff import AcceptedHandoff
from t02_capture_host_entry import run_transferred_supervisor
from t02_capture_local import LocalCaptureObservation, matches_local_capture
from t02_capture_local_windows import (
    _canonical,
    _digest,
    observe_local_capture,
    verify_checkout,
)
from t02_capture_packet import CapturePacket
from t02_capture_pipe_owner import CapturePipeOwner
from t02_capture_roles import hosted_capture_listener, hosted_capture_runtime
from t02_capture_supervisor import HostedRole
from t02_capture_trusted import Role
from t02_capture_windows_ownership import WindowsCaptureOwnership
from t02_event_https import GitHubHttps
from t02_event_types import Hold


def mono() -> int:
    return time.monotonic_ns() // 1_000_000


def wall() -> int:
    return time.time_ns() // 1_000_000


@dataclass(frozen=True)
class ReviewedHost:
    """Exact independently reviewed local pins, never sourced from packet or environment."""

    host: str
    checkout: Path
    git: Path
    git_sha256: str
    python: Path
    python_sha256: str
    profile_matches: Callable[[CapturePacket], bool] = lambda _: True

    def observe(self, packet: CapturePacket, deadline: int) -> LocalCaptureObservation:
        if (not self.profile_matches(packet) or _canonical(self.python, directory=False) != str(self.python)
            or _digest(self.python, mono, deadline) != self.python_sha256 or mono() >= deadline):
            raise Hold("capture interpreter identity held")
        return observe_local_capture(
            packet, platform.node,
            lambda path, end: verify_checkout(
                path, packet.approval.head, expected_checkout=self.checkout, expected_host=self.host,
                expected_origin="https://github.com/craigholland/lighthouse.git", git_executable=self.git,
                git_sha256=self.git_sha256, clock=mono, deadline_ms=end,
            ), mono, deadline,
        )


@dataclass(frozen=True)
class InstalledCapture:
    """Deployment-only binding absent from this offline draft."""

    host: ReviewedHost
    native: WindowsCaptureOwnership | None


def released_capture(role: Role | None = None) -> InstalledCapture | None:
    from t02_capture_installation import select_installation

    return select_installation(role)


def start_supervisor(bind: InstalledCapture) -> int:
    """Use fixed listener/runtime factories; effect attempts are independently authorized by the child."""
    raw = os.environ.get(ENVIRONMENT_KEY, "")
    native = bind.native
    if native is None:
        return 2
    def checked(accepted: AcceptedHandoff, deadline: int) -> LocalCaptureObservation:
        observed = bind.host.observe(accepted.packet, deadline)
        if mono() >= deadline or not matches_local_capture(accepted.packet, observed):
            raise Hold("capture child local binding held")
        return observed

    try:
        descriptor = InheritedCapture.accept(raw, mono, native.owns_pipe, native.owns_stop)
        def listener(accepted: AcceptedHandoff, job: int) -> HostedRole:
            checked(accepted, descriptor.peer.intake_ms)
            return hosted_capture_listener(accepted, job, descriptor, bind.host.python, mono, wall)

        receipt = run_transferred_supervisor(
            raw, mono, wall, native.owns_pipe, native.owns_stop, native.owns_jobs,
            listener,
            lambda accepted, job: hosted_capture_runtime(
                accepted, job, descriptor, checked(accepted, descriptor.peer.intake_ms), mono, wall,
            ),
            require_coordinator=True,
        )
        return 0 if receipt.phase == "confirmed" else 2
    except (Hold, OSError, ValueError, KeyboardInterrupt):
        return 2


def launch_coordinator(bind: InstalledCapture, packet: CapturePacket, refs: tuple[int, int]) -> str:
    """Claim once and dispatch only the fixed standalone coordinator."""
    window = CaptureWindow.from_packet(packet, wall, mono)
    source = CaptureEvidence(GitHubHttps(wall), wall)
    def allowed() -> bool:
        return (mono() < window.intake < window.cleanup
                and source.allows(packet.approval, *refs, before_ms=packet.intake_cutoff_ms)
                and mono() < window.intake)
    try:
        if not allowed() or not matches_local_capture(packet, bind.host.observe(packet, window.intake)) or not allowed():
            return "denied"
        store = open_existing_capture(packet)
    except (Hold, OSError, ValueError, KeyboardInterrupt):
        return "denied"
    try:
        store.claim(lambda: wall() if mono() < window.intake else packet.intake_cutoff_ms)
    except (Hold, OSError, ValueError, KeyboardInterrupt):
        return "admission-unknown"
    return dispatch_owned(
        packet, store, refs, window.intake, window.cleanup, mono,
        CaptureCoordinatorHost(bind.host.python, mono), CapturePipeOwner(mono), secrets.token_hex(32),
    )


def start_coordinator(bind: InstalledCapture) -> int:
    """Only the inherited IPC tuple enters; role Job handles are minted here."""
    raw = os.environ.get(ENVIRONMENT_KEY, "")
    native = bind.native
    if native is None:
        return 2
    try:
        descriptor = InheritedCapture.accept(raw, mono, native.owns_coordinator_pipe, native.owns_coordinator_stop)
        owned_entry(
            descriptor, mono, wall, CaptureEvidence(GitHubHttps(wall), wall),
            lambda packet, deadline: matches_local_capture(packet, bind.host.observe(packet, deadline)),
            lambda run: native.coordinator_objects(
                run.packet, run.store, CaptureWindow(descriptor.peer.intake_ms, descriptor.peer.cleanup_ms), run.refs,
            ),
        )
        return 0
    except (Hold, OSError, ValueError, KeyboardInterrupt):
        return 2
